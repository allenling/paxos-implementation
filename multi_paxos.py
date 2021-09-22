"""
"""
import enum
import sys
import json
import time
import yaml
import logging
import random
import curio
from curio import run, spawn
from curio.socket import *
from typing import Mapping, Sequence
import multi_paxos_msg
from common import logger


MSG_LIST = [multi_paxos_msg.PinigMsg,
            multi_paxos_msg.PongMsg,
            multi_paxos_msg.PrepareMsg,
            multi_paxos_msg.PrepareACKMsg,
            multi_paxos_msg.AcceptMsg,
            multi_paxos_msg.AcceptAckMsg,
            multi_paxos_msg.PrepareSyncACKMsg,
            multi_paxos_msg.PrepareSyncMsg,
            multi_paxos_msg.BatchAcceptMsg,
            multi_paxos_msg.BatchAcceptAckMsg,
            multi_paxos_msg.BatchChosenMsg,
            multi_paxos_msg.BatchChosenAckMsg,
            ]

MSG_TYPE_CLASS_MAP = {i.itype: i for i in MSG_LIST}

CLIENT_MSG_LIST = [multi_paxos_msg.ClientChooseCmd,
                   multi_paxos_msg.ClientNodeInfoCmd,
                   multi_paxos_msg.ClientGetLogDataCMD,
                   multi_paxos_msg.ClientDisableLeadershipCMD,
                   multi_paxos_msg.ClientIgnoreAcceptCMD,
                   multi_paxos_msg.ClientDisablePongCMD,
                   multi_paxos_msg.ClientGetRetryAcceptListCMD,
                   ]

CMD_TYPE_CLASS_MAP = {i.cmd_type: i for i in CLIENT_MSG_LIST}


def get_msg_obj_from_json(jdata):
    itype = multi_paxos_msg.MsgType(jdata["itype"])
    if itype == multi_paxos_msg.MsgType.CLIENT:
        client_cmd_class = CMD_TYPE_CLASS_MAP[multi_paxos_msg.ClientCMDType[jdata["data"]["cmd_type"]]]
        obj = client_cmd_class.from_json(jdata)
    else:
        msg_class = MSG_TYPE_CLASS_MAP[itype]
        obj = msg_class.from_json(jdata)
    return obj


def disjoint_yielder(node_id):
    # https://math.stackexchange.com/questions/51096/partition-of-n-into-infinite-number-of-infinite-disjoint-sets
    odd = 2*node_id - 1
    n = 1
    while True:
        yield odd * (2**n)
        n += 1
    return


def disjoint_from_lamport(node_id):
    # order.node_id
    # 1.1 < 1.2 < 10.1 < 11.3 < 12.1
    # compare order first, then compare node_id
    index = 1
    while True:
        yield "%s.%s" % (index, node_id)
        index += 1
    return


class AckEvt:

    def __init__(self, pn, resp_type=multi_paxos_msg.MsgType.PREPARE_ACK):
        self.pn = pn
        self.evt = curio.Event()
        self.ack_msgs = []
        self.status = None
        self.resp_type = resp_type
        self.name = f"AckEvt<{pn}, {resp_type.name}>"
        return

    async def wait(self):
        try:
            result = await curio.timeout_after(multi_paxos_msg.NODE_TIMEOUT, self.evt.wait)
        except curio.TaskTimeout:
            self.status = multi_paxos_msg.MsgStatus.TIMEOUT
        return

    async def cancel(self):
        self.status = multi_paxos_msg.MsgStatus.CANCEL
        await self.evt.set()
        return

    def is_suc(self):
        return self.status and self.status == multi_paxos_msg.MsgStatus.SUC

    def validate_ack_nsg(self, ack_msg):
        ack_info = f"ack msg {ack_msg.prepare_pn} {ack_msg.from_node} {ack_msg.itype.name}"
        ret = True
        if self.status is not None:
            logger.info(f"{self.name} have status {self.status.name}, so ignore this ack!")
            ret = False
        if ack_msg.itype != self.resp_type:
            logger.error(f"{self.name} got a different msg type of ack {ack_info}")
            ret = False
        if ack_msg.prepare_pn != self.pn:
            logger.info(f"{self.name} got a different pn of ack {ack_info}, so ignore this ack!")
            ret = False
        return ret, ack_info

    async def get_ack(self, ack_msg, quorum_check_func):
        ret, ack_info = self.validate_ack_nsg(ack_msg)
        if not ret:
            return
        logger.debug(f"{self.name} get ack msg {ack_info}")
        self.ack_msgs.append(ack_msg)
        nodes = [i.from_node for i in self.ack_msgs]
        if quorum_check_func(nodes):
            self.status = multi_paxos_msg.MsgStatus.SUC
            await self.evt.set()
        return

    def get_ack_sync(self, ack_msg, quorum_check_func):
        ret, ack_info = self.validate_ack_nsg(ack_msg)
        if not ret:
            return False
        self.ack_msgs.append(ack_msg)
        nodes = [i.from_node for i in self.ack_msgs]
        return quorum_check_func(nodes)

    def get_max_prepare_ack_pn(self):
        return max([i.prepare_pn for i in self.ack_msgs], default=self.pn)

    def get_all_success_msgs(self):
        msgs = [msg for msg in self.ack_msgs if msg.is_suc()]
        return msgs


class LogDataState(enum.Enum):
    timeout = 0
    accpeted = 1
    chosen = 2
    empty = 4


class LogData:

    def __init__(self, pos: int, value=None, req_id=None, state=LogDataState.empty, prepare_pn=-1):
        self.pos = pos
        self.value = value
        self.req_id = req_id
        self.state = state
        self.prepare_pn = prepare_pn
        return

    def __str__(self):
        return "LogData<pos=%s, value=%s, req_id=%s, state=%s, pn%s>" % (self.pos, self.value, self.req_id, self.state.name, self.prepare_pn,)

    def __repr__(self):
        return self.__str__()

    def to_tuple(self):
        return self.pos, self.value, self.req_id, self.state.name, self.prepare_pn

    def to_dict(self):
        return {"pos": self.pos, "value": self.value, "req_id": self.req_id,
                "state": self.state.name, "prepare_pn": self.prepare_pn,
                }


class ReqidInfo:

    def __init__(self, req_id, pos, state: multi_paxos_msg.LearnState):
        self.req_id = req_id
        self.pos = pos
        self.state = state
        return


class LogDataManager:

    def __init__(self, n=100, alpha=1):
        self.log_data = [LogData(i) for i in range(n)]
        self.all_chosen_index = None  # all value whose index is less then or equal to all_chosen_index are on chosen state
        self.log_index = -1
        self.alpha = alpha or float("inf")
        return

    def get_next_log_index(self):
        all_chosen_index = self.all_chosen_index or -1
        if self.log_index - all_chosen_index >= self.alpha:
            # if you get None return, then you need to call this method again to get log index
            return None
        self.log_index += 1
        if self.log_index >= len(self.log_data) * 2 // 3:
            start_pos = self.log_data[-1].pos + 1
            extra_data = [LogData(i) for i in range(start_pos, start_pos + len(self.log_data))]
            self.log_data.extend(extra_data)
        return self.log_index

    def is_chosen(self, pos):
        return self.log_data[pos].state == LogDataState.chosen

    def get_data(self, pos):
        return self.log_data[pos]

    def update_all_chosen_index(self, current_chosen_index):
        my_chosen_index = -1 if self.all_chosen_index is None else self.all_chosen_index
        if my_chosen_index > current_chosen_index:
            return
        if self.log_data[my_chosen_index + 1].state != LogDataState.chosen:
            return
        self.all_chosen_index = my_chosen_index + 1
        while self.all_chosen_index < self.log_index:
            next_index = self.all_chosen_index + 1
            if self.log_data[next_index].state != LogDataState.chosen:
                break
            self.all_chosen_index += 1
            # TODO: execute cmd!
        return

    def mark_slot_accepted(self, prepare_pn, pos, value, req_id):
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.accpeted, prepare_pn)
        return

    def mark_slot_chosen(self, prepare_pn, pos, value, req_id):
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.chosen, prepare_pn)
        self.update_all_chosen_index(pos)
        logger.debug(f"mark_slot_chosen all_chosen_index {self.all_chosen_index}")
        return

    def get_batch_chosen_list(self, node_name, node_all_chosen_index):
        ret = []
        if self.all_chosen_index is None:
            return ret
        if node_all_chosen_index is None:
            ret = list(range(self.all_chosen_index+1))
        elif self.all_chosen_index > node_all_chosen_index:
            ret = list(range(node_all_chosen_index+1, self.all_chosen_index+1))
        elif self.all_chosen_index < node_all_chosen_index:
            logger.error(f"why all_chosen_index in {node_name} is larger than mine({self.all_chosen_index}) ????????????")
        elif self.all_chosen_index == node_all_chosen_index:
            pass
        return ret

    def sync_prepare_data(self, prepare_pn, msgs: Sequence[multi_paxos_msg.PrepareSyncACKMsg]):
        min_index, max_index = msgs[0].min_index, msgs[0].max_index
        my_sync_data: Sequence[LogData] = self.log_data[min_index: max_index + 1]
        datas = []
        for i in msgs:
            datas.append([LogData(i[0], i[1], i[2], LogDataState(i[3]), i[4]) for i in i.sync_data])
        datas.append(my_sync_data)
        res = []
        for i in range(len(datas[0])):
            prepare_datas = [j[i] for j in datas]
            logger.dbeug(f"sync {prepare_datas}")
            chosen = LogData(prepare_datas[0].pos, value="no_op", req_id=None, state=LogDataState.chosen, prepare_pn=prepare_pn)
            prepare_datas = [i for i in prepare_datas if i.state != LogDataState.empty]
            if prepare_datas:
                prepare_datas = sorted(prepare_datas, key=lambda n: -n.prepare_pn)
                chosen.value = prepare_datas[0].value
                chosen.req_id = prepare_datas[0].req_id
            res.append(chosen)
        for i in res:
            logger.debug(f"set {i} chosen")
            self.log_data[i.pos] = i
        self.log_index = max_index
        self.update_all_chosen_index(max_index)
        logger.info(f"prepare sync done {self.all_chosen_index}, {self.log_index}")
        return


class Config:

    def __init__(self, extra_yaml_paths=None):
        with open("multi_paxos_conf.yaml", "r") as f:
            self.conf = yaml.safe_load(f)
        if extra_yaml_paths:
            for i in extra_yaml_paths:
                self.update_extra_yaml(i)
        return

    def update_extra_yaml(self, yaml_path):
        with open(yaml_path, "r") as f:
            new_conf = yaml.safe_load(f)
        self.conf.update(new_conf)
        return

    def __getitem__(self, key):
        return self.conf[key]

    def __setitem__(self, key, value):
        self.conf[key] = value
        return


class LogStateMatchine:

    def __init__(self, my_id, conf):
        self.node_name = my_id
        self.conf = conf
        self.verbose_name = "Machine<%s>" % my_id
        level = self.conf["log_level"].upper()
        if len(sys.argv) >= 3:
            level = getattr(logging, sys.argv[2].upper())
        logging.getLogger("paxos").setLevel(level)
        self.addr = self.conf["nodes"][my_id].split(":")
        self.addr[1] = int(self.addr[1])
        self.addr = tuple(self.addr)
        self.nodes_map = {}
        for k, v in self.conf["nodes"].items():
            if k == my_id:
                continue
            v = v.split(":")
            v[1] = int(v[1])
            self.nodes_map[k] = tuple(v)
        self.node_names = list(self.nodes_map.keys())
        self.url_to_node_map = {url: name for name, url in self.nodes_map.items()}
        self.gossip_msg = multi_paxos_msg.GossipMsg(self.node_names, my_id)
        self.handler_map = {multi_paxos_msg.MsgType.PING: self.handle_ping,
                            multi_paxos_msg.MsgType.PONG: self.handle_pong,
                            multi_paxos_msg.MsgType.PREPARE: self.handle_prepare,
                            multi_paxos_msg.MsgType.PREPARE_ACK: self.handle_prepare_ack,
                            multi_paxos_msg.MsgType.ACCEPT: self.handle_accept,
                            multi_paxos_msg.MsgType.ACCEPT_ACK: self.handle_accept_ack,
                            multi_paxos_msg.MsgType.PREPARE_SYNC: self.handle_prepare_sync,
                            multi_paxos_msg.MsgType.PREPARE_SYNC_ACK: self.handle_prepare_sync_ack,
                            multi_paxos_msg.MsgType.BATCH_ACCEPT: self.handle_batch_accept,
                            multi_paxos_msg.MsgType.BATCH_ACCPET_ACK: self.handle_batch_accept_ack,
                            multi_paxos_msg.MsgType.BATCH_CHOSEN: self.handle_batch_chosen,
                            multi_paxos_msg.MsgType.BATCH_CHOSEN_ACK: self.handle_batch_chosen_ack,
                            }
        self.client_hanlder_map = {multi_paxos_msg.ClientCMDType.CHOOSE: self.handle_choose,
                                   multi_paxos_msg.ClientCMDType.INFO: self.handle_info,
                                   multi_paxos_msg.ClientCMDType.GET_LOG_DATA: self.handle_get_log_data,
                                   multi_paxos_msg.ClientCMDType.DISABLE_LEADERSHIP: self.handle_disable_leadership,
                                   multi_paxos_msg.ClientCMDType.IGNORE_ACCEPT: self.handle_ignore_accept_msg,
                                   multi_paxos_msg.ClientCMDType.DISABLE_PONG: self.handle_pong,
                                   multi_paxos_msg.ClientCMDType.GET_RETRY_ACCEPT_LIST: self.handle_get_retry_accept_list,
                                   }
        self.cluster_state = multi_paxos_msg.ClusterState.unhealthy
        self._stop = False
        self.election_delay_ms = -1
        self.prepare_pn = -1
        self.accepted_pn = -1
        self.accepted_value = None
        alpha = self.conf["pipeline_alpha"]
        alpha = float("-inf") if alpha is None or alpha <= 0 else alpha
        self.log_data_manager = LogDataManager(alpha=alpha)
        self.last_prepare_time = 0
        self.prepare_ack_evt = None
        self.prepare_sync_ack_evt = None
        self.accept_ack_evts = {}  # {pos: ActEvt}
        self.pn_yielder = disjoint_yielder(my_id)
        self.send_msg_queue = curio.Queue()
        self.retry_accept_data = {}  # {pos: [pos, value, req_id], ...}
        self.req_id_history: Mapping[str, ReqidInfo] = {}
        self.chosen_broadcast_list = {name: {} for name in self.node_names}  # {node_name: {pos: [pos, value, req_id], ...}, ...}
        self._set_quorums()

        self.client_settings = {"never_attempt_to_acquire_leadership": False,
                                "disable_pong": False,
                                "ignore_accept": False,
                                }
        if self.conf["disable_leadership"] and self.node_name in self.conf["disable_leadership"]:
            self.client_settings["never_attempt_to_acquire_leadership"] = True
        if self.conf["disable_pong"] and self.node_name in self.conf["disable_pong"]:
            self.client_settings["disable_pong"] = True
        if self.conf["ignore_accept"] and self.node_name in self.conf["ignore_accept"]:
            self.client_settings["ignore_accept"] = True
        logger.info(f"my client settings: {self.client_settings}")
        return

    def _set_quorums(self):
        self.half = len(self.node_names) // 2
        return

    def get_Q1_recipients(self):
        return self.node_names

    def get_Q2_recipients(self):
        return self.node_names

    def check_Q1_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.half

    def check_Q2_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.half

    def reset_batch_task_data(self):
        self.retry_accept_data = {}
        self.chosen_broadcast_list = {name: {} for name in self.node_names}
        return

    def get_next_pn(self):
        res = next(self.pn_yielder)
        while res <= self.prepare_pn:
            res = next(self.pn_yielder)
        return res

    async def io_server(self):
        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind(self.addr)
        sock.listen(5)
        # 2 connect to 1, 3 connect to 1 and 2
        connect_to = sorted(self.nodes_map.keys())
        for node_name in connect_to:
            if node_name < self.node_name:
                await spawn(self.connect_to_node, node_name, daemon=True)
            await spawn(self.send_node_pong, node_name, daemon=True)
        await spawn(self.check_state, daemon=True)
        await spawn(self.send_node_coro, daemon=True)
        await spawn(self.background_batch_accept, daemon=True)
        await spawn(self.background_batch_chosen, daemon=True)
        logger.info("%s io Server listening at %s" % (self.verbose_name, self.addr))
        async with sock:
            while not self._stop:
                try:
                    client, addr = await curio.timeout_after(len(self.node_names) + 2, sock.accept)
                except curio.TaskTimeout:
                    continue
                await spawn(self.recv_from_node, client, addr, daemon=True)
        logger.info("%s io Server return" % self.verbose_name)
        return

    async def recv_from_node(self, client, addr):
        logger.info("%s recv_from_node from %s" % (self.verbose_name, addr))
        node_name = None
        client_name = None
        async with client:
            while not self._stop:
                try:
                    data_bytes = await client.recv(multi_paxos_msg.IOMSG_FIX_LEN)
                except Exception as e:
                    logger.error(f"{self.verbose_name} recv data from {addr} error {str(e)}")
                    if node_name:
                        self.gossip_msg.set_node_sock(node_name, None)
                        if node_name < self.node_name:
                            await spawn(self.connect_to_node, node_name, daemon=True)
                    elif client_name:
                        logger.info(f"client {client_name} close connection")
                    else:
                        logger.warning("we lost a unknown connection")
                    await client.close()
                    return
                if not data_bytes:
                    logger.error(f"{self.verbose_name} get empty from {addr}! means {node_name}/{client_name} has been closed")
                    if node_name:
                        self.gossip_msg.set_node_sock(node_name, None)
                        if node_name < self.node_name:
                            await spawn(self.connect_to_node, node_name, daemon=True)
                    if client_name:
                        logger.info(f"client {client_name} close connection")
                    await client.close()
                    return
                data = data_bytes.decode().strip("0")
                logger.debug("recv data %s", data)
                jdata = json.loads(data)
                try:
                    msg_obj = get_msg_obj_from_json(jdata)
                except Exception as e:
                    logger.error(f"?????? {jdata}")
                    logger.error(f"!!!!!! {data}")
                    raise e
                if node_name is None and client_name is None:
                    logger.info(f"{self.verbose_name} recv first msg from node {msg_obj.from_node} {addr}")
                node_name = msg_obj.from_node
                if msg_obj.itype == multi_paxos_msg.MsgType.CLIENT:
                    client_name = node_name
                    node_name = None
                    logger.info("%s get cmd msg %s from client %s", self.verbose_name, msg_obj.cmd_type, client_name)
                    # one cmd
                    handle_func = self.client_hanlder_map[msg_obj.cmd_type]
                    resp = await handle_func(msg_obj)
                    await client.sendall(resp)
                    continue
                logger.debug("%s get %s msg from %s" % (self.verbose_name, msg_obj.itype, node_name))
                if not self.gossip_msg.get_node_sock(msg_obj.from_node):
                    self.gossip_msg.set_node_sock(msg_obj.from_node, client)
                handle_func = self.handler_map[msg_obj.itype]
                await spawn(handle_func, msg_obj, daemon=True)
        logger.info("%shandle_iomsg connection<%s> closed" % (self.verbose_name, addr))
        return

    async def send_node_coro(self):
        prev_fail_dict = {}
        while not self._stop:
            node_name, msg = await self.send_msg_queue.get()
            if node_name not in prev_fail_dict:
                prev_fail_dict[node_name] = 0
            try:
                sock = self.gossip_msg.get_node_sock(node_name)
                logger.debug("%s is sending msg(%s) to node %s", self.verbose_name, msg.itype, node_name)
                if not sock:
                    if time.time() - prev_fail_dict[node_name] >= 10:
                        logger.warning(f"i have None sock for node {node_name}, sending terminated")
                        prev_fail_dict[node_name] = time.time()
                    continue
                await sock.sendall(msg.get_bytes())
            except Exception as e:
                logger.error("%s send node %s msg %s error", self.verbose_name, node_name, msg, exc_info=True)
                await sock.close()
        return

    async def connect_to_node(self, node_name, wait_second=1):
        # sleep 1 second at least to wait for connection release completely
        await curio.sleep(wait_second)
        logger.info("%s start to connect to %s", self.verbose_name, node_name)
        sock = socket(AF_INET, SOCK_STREAM)
        node_url = self.nodes_map[node_name]
        next_wait_time = wait_second * 1000
        prev_fail_time = time.time()
        while not self._stop:
            try:
                await sock.connect(node_url)
            except Exception as e:
                next_wait_time += random.randint(1000, 2000)
                if prev_fail_time - time.time() >= 10:
                    logger.info("%s connect to node<%s> fail, retry after %s(ms)", self.verbose_name, node_name, next_wait_time, exc_info=True)
                    prev_fail_time = time.time()
                await curio.sleep(next_wait_time / 1000)
                continue
            break
        logger.info("%s has connected to %s!!!!" % (self.verbose_name, node_name))
        self.gossip_msg.set_node_sock(node_name, sock)
        await spawn(self.recv_from_node, sock, node_url, daemon=True)
        return

    async def send_node_pong(self, node_name):
        while not self._stop:
            await curio.sleep(multi_paxos_msg.NODE_TIMEOUT // 3 + random.randint(100, 500) / 1000)
            if self.client_settings["disable_pong"]:
                continue
            pong_msg = multi_paxos_msg.PongMsg.from_gossip_msg(self.gossip_msg, self)
            pong_msg.set_from_node(self.node_name)
            await self.send_msg_queue.put((node_name, pong_msg))
        return

    def detect_partition_and_launch_prepare(self, online_nodes):
        any_others_see_leader = [i for i in online_nodes if i[1]["leader_online"]]
        need_elect = False
        # we are in a majority set
        if not any_others_see_leader and self.gossip_msg.is_leader_offline():
            # all of other nodes can't connect to leader, and i can't see the leader neither, then start a new election!
            # {1, 2}, {3, 4, 5}
            need_elect = True
        elif any_others_see_leader and self.gossip_msg.is_leader_offline():
            # {1, 3}, {2}, {3, 4, 5}, we are 4, and we know 3 can see leader
            online_node_leader_cluster_state = [self.gossip_msg.get_node_leader_cluster_state(i[0]) for i in
                                                any_others_see_leader]
            need_elect = True
            # 3 says that the leader is on healthy state, then we don't start a new election
            # otherwise, feel free to start a new election!
            if any([i == multi_paxos_msg.ClusterState.healthy.name for i in online_node_leader_cluster_state]):
                # check there is any node can see leader is on healthy state
                # because 5 can't connect to leader, so the leaders cluster state may be stale
                need_elect = False
        elif not any_others_see_leader and self.gossip_msg.is_leader_online():
            # {1, 3}, {2}, {3, 4, 5}, we are 3, and we know 4 and 5 can't see leader
            # and we can see leader, we need to check leader's cluster_state
            leader_cluster_state = self.gossip_msg.get_leader_cluster_state()
            if leader_cluster_state == multi_paxos_msg.ClusterState.unhealthy.name:
                need_elect = True
        return need_elect

    async def start_a_new_preparation(self, need_elect):
        if need_elect and self.election_delay_ms == -1:
            # random backoff
            self.election_delay_ms = random.randint(2000, 3000)  # 2s - 3s
            logger.info(f"{self.verbose_name} need to start a election, delay {self.election_delay_ms}(ms)")
            await spawn(self.prepare, daemon=True)
        return

    async def check_state(self):
        while not self._stop:
            await curio.sleep(multi_paxos_msg.NODE_TIMEOUT)
            online_nodes = self.gossip_msg.update_nodes_status()
            any_others_see_leader = [i for i in online_nodes if i[1]["leader_online"]]
            same_pn_online_nodes = [i for i in online_nodes if i[1]["prepare_pn"] != -1 and i[1]["prepare_pn"] == self.prepare_pn]
            if len(online_nodes) < self.half:
                if self.cluster_state == multi_paxos_msg.ClusterState.healthy:
                    # we are in a minority set, so set unhealthy state
                    self.cluster_state = multi_paxos_msg.ClusterState.unhealthy
                    logger.info(f"{self.verbose_name} switch to unhealthy state!!!!")
                msg = "im(%s) in a minority set(size=%s)" % (self.verbose_name, len(online_nodes) + 1)
                if self.gossip_msg.is_leader(self.node_name):
                    msg += " and im the leader"
                if not self.gossip_msg.get_leader():
                    msg += " and no leader elected!"
                elif not any_others_see_leader:
                    msg += " and no other nodes can see the leader %s!" % self.gossip_msg.get_leader()
                logger.info(msg)
                continue
            if len(same_pn_online_nodes) < self.half:
                if self.cluster_state == multi_paxos_msg.ClusterState.healthy:
                    logger.info(f"{self.verbose_name} in a minority pn({self.prepare_pn}) set of majority set")
                    self.cluster_state = multi_paxos_msg.ClusterState.unhealthy
            elif self.gossip_msg.is_leader_offline():
                if self.cluster_state == multi_paxos_msg.ClusterState.healthy:
                    logger.info(f"{self.verbose_name} lost leader")
                    self.cluster_state = multi_paxos_msg.ClusterState.unhealthy
            elif self.cluster_state == multi_paxos_msg.ClusterState.unhealthy:
                logger.info(f"{self.verbose_name} switch to healthy state!!!!")
                self.cluster_state = multi_paxos_msg.ClusterState.healthy
            need_elect = self.detect_partition_and_launch_prepare(online_nodes)
            await self.start_a_new_preparation(need_elect)
        return


    async def handle_ping(self, msg_obj):
        """
        response pong
        """
        from_node = msg_obj.from_node
        pong_msg = multi_paxos_msg.PongMsg.from_gossip_msg(self.gossip_msg, self)
        pong_msg.set_from_node(self.node_name)
        await self.send_msg_queue.put((from_node, pong_msg))
        return

    async def handle_pong(self, msg_obj: multi_paxos_msg.PongMsg):
        """
        update gossip
        """
        # TODO: save prepare proposal number into file
        from_node = msg_obj.from_node
        self.gossip_msg.update_node_last_pong_time(from_node)
        self.gossip_msg.set_node_online(from_node, msg_obj.get_data())
        if msg_obj.prepare_pn < self.prepare_pn:
            if from_node == self.gossip_msg.get_leader():
                logger.info("we get the old leader, remove the leader nomination")
                self.gossip_msg.set_leader(None)
            return
        my_leader = self.gossip_msg.get_leader()
        if msg_obj.prepare_pn > self.prepare_pn:
            if msg_obj.leader:
                if msg_obj.leader == self.node_name and self.prepare_pn == -1:
                    # we were the leader but now restart, consequently, we need to start a new preparation later!
                    return
                # when B get a pong msg from A, it is aware of someone(C) has risen the proposal number
                # clear leader and wait for update
                logger.info("%s(pn=%s, leader=%s) upgrade new leader(%s) base on pong from node %s, pn=%s",
                            self.verbose_name, self.prepare_pn, my_leader, msg_obj.leader, from_node, msg_obj.prepare_pn
                            )
                self.prepare_pn = msg_obj.prepare_pn
                self.reset_batch_task_data()
                self.accept_ack_evts = {}
                self.gossip_msg.set_leader(msg_obj.leader)
            return
        # msg_obj.prepare_pn == self.prepare_pn:
        if not msg_obj.leader:
            return
        if not my_leader:
            logger.info(f"{self.verbose_name}({self.node_name}) update leader to be {msg_obj.leader}")
            self.gossip_msg.set_leader(msg_obj.leader)
        if self.gossip_msg.is_leader(self.node_name):
            # sync log data
            new_batch_chosen_index_list = self.log_data_manager.get_batch_chosen_list(from_node, msg_obj.all_chosen_index)
            for i in new_batch_chosen_index_list:
                if i not in self.chosen_broadcast_list[from_node]:
                    data = self.log_data_manager.get_data(i)
                    self.chosen_broadcast_list[from_node][i] = [data.pos, data.value, data.req_id]
        return

    async def prepare(self):
        if self.client_settings["never_attempt_to_acquire_leadership"]:
            logger.info("%s never attempt to acquire leadership", self.verbose_name)
            self.election_delay_ms = -1
            return
        await curio.sleep(self.election_delay_ms / 1000)
        if self.gossip_msg.is_leader_online() and self.gossip_msg.get_leader_cluster_state() == multi_paxos_msg.ClusterState.healthy:
            logger.info(f"{self.verbose_name} have leader online and healthy, no need to start a election!")
            self.election_delay_ms = -1
            return
        if time.time() - self.last_prepare_time < multi_paxos_msg.NODE_TIMEOUT:
            logger.info(f"{self.verbose_name} got prepare request at {self.last_prepare_time}, we cancel this preparation")
            self.election_delay_ms = -1
            return
        # reset leader
        self.gossip_msg.set_leader(None)
        self.prepare_pn = self.get_next_pn()
        logger.info("@@@@@@@@@@@@%s is going to prepare, prepare_pn=%s !!!!!", self.verbose_name, self.prepare_pn)
        prepare_msg = multi_paxos_msg.PrepareMsg(self.prepare_pn)
        prepare_msg.set_from_node(self.node_name)
        self.prepare_ack_evt = AckEvt(self.prepare_pn, multi_paxos_msg.MsgType.PREPARE_ACK)
        for node_name in self.get_Q1_recipients():
            await self.send_msg_queue.put((node_name, prepare_msg))
        # wait for majority
        await self.prepare_ack_evt.wait()
        logger.info(f"{self.verbose_name} wait prepare done, got status {self.prepare_ack_evt.status.name}")
        self.prepare_pn = max(self.prepare_pn, self.prepare_ack_evt.get_max_prepare_ack_pn())
        if self.prepare_ack_evt.is_suc():
            # we are the leader!
            self.gossip_msg.set_leader(self.node_name)
            self.cluster_state = multi_paxos_msg.ClusterState.healthy
            logger.info(f"############## I({self.verbose_name}, pn={self.prepare_pn}) am the leader!!!!!!!!")
            # sync log data and broadcast chosen
            msgs = self.prepare_ack_evt.get_all_success_msgs()
            # [min_index, max_index], left and right both are closed
            all_chosen_indexs = [[i.from_node, i.all_chosen_index] for i in msgs]
            all_chosen_indexs += [[self.node_name, self.log_data_manager.all_chosen_index]]
            logger.info(f"prepare get all_chosen_indexs: {all_chosen_indexs}")
            all_chosen_indexs = [i[1] for i in all_chosen_indexs]
            if None in all_chosen_indexs:
                min_index = None
            else:
                min_index = min(all_chosen_indexs)
            max_index_list = [i.log_index for i in msgs] + [self.log_data_manager.log_index]
            logger.info(f"max_index list {max_index_list}")
            max_index = max(max_index_list)
            logger.info(f"min index {min_index} max index {max_index}")
            if max_index > -1 and min_index != max_index:
                min_index = min_index or 0
                logger.info(f"{self.verbose_name} is going to sync prepare data, [{min_index}, {max_index}]")
                prepare_sync_msg = multi_paxos_msg.PrepareSyncMsg()
                prepare_sync_msg.set_prepare_pn(self.prepare_pn)
                prepare_sync_msg.set_from_node(self.node_name)
                prepare_sync_msg.set_min_index(min_index)
                prepare_sync_msg.set_max_index(max_index)
                self.prepare_sync_ack_evt = AckEvt(self.prepare_pn, multi_paxos_msg.MsgType.PREPARE_SYNC_ACK)
                for node_name in self.get_Q1_recipients():
                    await self.send_msg_queue.put((node_name, prepare_sync_msg))
                await self.prepare_sync_ack_evt.wait()
                logger.info(f"{self.verbose_name} wait prepare sync done, got status {self.prepare_sync_ack_evt.status.name}")
                if self.gossip_msg.is_leader(self.node_name) and self.prepare_sync_ack_evt.is_suc():
                    msgs = self.prepare_sync_ack_evt.get_all_success_msgs()
                    self.log_data_manager.sync_prepare_data(self.prepare_pn, msgs)
            elif max_index == -1:
                logger.info(f"{self.verbose_name} no need to sync prepare data, max_index is -1")
            elif min_index == max_index:
                logger.info(f"{self.verbose_name} no need to sync prepare data, min_index == max_index == {min_index}")
        self.prepare_sync_ack_evt = None
        self.prepare_ack_evt = None
        self.election_delay_ms = -1
        return

    async def handle_prepare(self, msg_obj: multi_paxos_msg.PrepareMsg):
        """
        we only accept prepare when no one can see a leader!
        """
        if time.time() - self.last_prepare_time < multi_paxos_msg.NODE_TIMEOUT:
            # prevent too many preparation request coming
            logger.debug("%s got too many prepare msg, ignore prepare msg from node %s",
                         self.verbose_name,
                         msg_obj.from_node)
            return
        self.last_prepare_time = time.time()
        prepare_ack_msg = multi_paxos_msg.PrepareACKMsg()
        prepare_ack_msg.set_from_node(self.node_name)
        logger.info("%s, pn=%s handle prepare from node %s, pn %s",
                    self.verbose_name, self.prepare_pn, msg_obj.from_node, msg_obj.prepare_pn,
                    )
        if msg_obj.prepare_pn <= self.prepare_pn:
            prepare_ack_msg.set_status_fail()
            logger.info("%s(pn=%s) get a prepare msg with smaller pn from node %s(pn=%s)", self.verbose_name, self.prepare_pn,
                        msg_obj.prepare_pn, msg_obj.from_node)
        else:
            if self.prepare_ack_evt:
                await self.prepare_ack_evt.cancel()
            if self.prepare_sync_ack_evt:
                await self.prepare_sync_ack_evt.cancel()
            self.prepare_pn = msg_obj.prepare_pn
            self.gossip_msg.set_leader(None)
            self.reset_batch_task_data()
            self.accept_ack_evts = {}
            prepare_ack_msg.set_status_success()
            prepare_ack_msg.set_all_chosen_index(self.log_data_manager.all_chosen_index)
            prepare_ack_msg.set_log_index(self.log_data_manager.log_index)
            logger.info("%s send prepare ack suc to node %s, all_chosen_index %s, log_index %s, prepare_pn %s",
                        self.verbose_name, msg_obj.from_node, self.log_data_manager.all_chosen_index, self.log_data_manager.log_index,
                        self.prepare_pn)
        prepare_ack_msg.set_prepare_pn(self.prepare_pn)
        await self.send_msg_queue.put((msg_obj.from_node, prepare_ack_msg))
        return

    async def handle_prepare_ack(self, msg_obj: multi_paxos_msg.PrepareACKMsg):
        if msg_obj.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare ack from node %s with pn %s", self.verbose_name, msg_obj.from_node, msg_obj.prepare_pn)
            return
        if msg_obj.prepare_pn > self.prepare_pn:
            logger.warning("%s get a larger pn %s prepare ack from node %s, thats weird")
            return
        if not self.prepare_ack_evt:
            logger.error("self.prepare_ack_evt is None, why?")
            return
        logger.info(f"handle_prepare_ack {msg_obj.from_node} {msg_obj.get_data()}")
        await self.prepare_ack_evt.get_ack(msg_obj, self.check_Q1_quorum)
        return

    async def handle_prepare_sync(self, msg: multi_paxos_msg.PrepareSyncMsg):
        if msg.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare sync from node %s with pn %s", self.verbose_name, msg.from_node, msg.prepare_pn)
            return
        if msg.prepare_pn > self.prepare_pn:
            logger.warning("%s(pn=%s) get a larger pn %s prepare sync from node %s, thats weird",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn,
                           msg.from_node)
            return
        logger.info(f"handle_prepare_sync {msg.min_index}, {msg.max_index}")
        data = self.log_data_manager.log_data[msg.min_index: msg.max_index+1]
        resp = multi_paxos_msg.PrepareSyncACKMsg()
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_from_node(self.node_name)
        resp.set_sync_data(data)
        resp.set_status_success()
        resp.set_min_max_index(msg.min_index, msg.max_index)
        await self.send_msg_queue.put((msg.from_node, resp))
        return

    async def handle_prepare_sync_ack(self, msg: multi_paxos_msg.PrepareSyncACKMsg):
        if msg.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare sync ack from node %s with pn %s", self.verbose_name, msg.from_node, msg.prepare_pn)
            return
        if msg.prepare_pn > self.prepare_pn:
            logger.warning("%s get a larger pn %s prepare sync ack from node %s, thats weird")
            return
        if not self.prepare_sync_ack_evt:
            logger.error("self.prepare_sync_ack_evt is None, why?")
            return
        await self.prepare_sync_ack_evt.get_ack(msg, self.check_Q1_quorum)
        return

    async def handle_choose(self, choose_cmd: multi_paxos_msg.ClientChooseCmd):
        resp = multi_paxos_msg.ClientChooseResult()
        resp.set_from_node(self.node_name)
        if not self.gossip_msg.is_leader(self.node_name):
            logger.warning("I am not the leader, stop asking me to choose a value")
            resp.set_status_fail()
            if self.gossip_msg.get_leader():
                resp.set_reason("i am not the leader, the leader is %s" % self.gossip_msg.get_leader())
            else:
                resp.set_reason("the leader is unknown")
            return resp.get_bytes()
        elif self.cluster_state == multi_paxos_msg.ClusterState.unhealthy:
            resp.set_status_fail()
            resp.set_reason("the cluster is unhealthy state!")
            return resp.get_bytes()
        value = choose_cmd.value
        req_id = choose_cmd.req_id
        req_id_state = self.req_id_history.get(req_id, None)
        if req_id_state == multi_paxos_msg.LearnState.suc:
            resp.set_status_fail()
            resp.set_reason("request succeeded, do not issue again!")
            return resp.get_bytes()
        elif req_id_state == multi_paxos_msg.LearnState.timeout:
            resp.set_status_fail()
            resp.set_reason("request is waiting for chosen, do not issue again!")
            return resp.get_bytes()
        while True:
            log_index = self.log_data_manager.get_next_log_index()
            if log_index is not None:
                break
            await curio.sleep(0.01)
        accept_msg = multi_paxos_msg.AcceptMsg()
        accept_msg.set_from_node(self.node_name)
        accept_msg.set_prepare_pn(self.prepare_pn)
        accept_msg.set_pos_and_value(log_index, value)
        accept_msg.set_req_id(req_id)
        accept_ack_evt = AckEvt(self.prepare_pn, resp_type=multi_paxos_msg.MsgType.ACCEPT_ACK)
        self.accept_ack_evts[log_index] = accept_ack_evt
        for node_name in self.get_Q2_recipients():
            await self.send_msg_queue.put((node_name, accept_msg))
        # wait for majority
        await accept_ack_evt.wait()
        logger.debug(f"{self.verbose_name} wait accept for log index {log_index}, value {value} return status {accept_ack_evt.status.name}")
        del self.accept_ack_evts[log_index]
        if accept_ack_evt.is_suc():
            resp.set_status_success()
            self.log_data_manager.mark_slot_chosen(self.prepare_pn, log_index, value, req_id)
            for name in self.get_Q2_recipients():
                self.chosen_broadcast_list[name][log_index] = [log_index, value, req_id]
        else:
            resp.set_status_timeout()
            resp.set_reason("i lost some nodes")
            max_pn = accept_ack_evt.get_max_prepare_ack_pn()
            if max_pn > self.prepare_pn:
                logger.warning(f"i lost our leadership when recv accept ack for pos {log_index}, value {value},"
                               f"max_pn {max_pn}, my prepare_pn {self.prepare_pn}",
                               )
                new_leader = self.gossip_msg.get_leader()
                msg = "i lost my leadership!"
                if new_leader:
                    msg += " new leader is {new_leader}"
                resp.set_reason(msg)
            else:
                self.accept_ack_evts[log_index] = AckEvt(self.prepare_pn, resp_type=multi_paxos_msg.MsgType.BATCH_ACCPET_ACK)
                self.retry_accept_data[log_index] = [log_index, value, req_id]
                self.req_id_history[req_id] = ReqidInfo(log_index, req_id, multi_paxos_msg.LearnState.timeout)
                self.log_data_manager.mark_slot_accepted(self.prepare_pn, log_index, value, req_id)
        return resp.get_bytes()

    async def handle_accept(self, msg_obj: multi_paxos_msg.AcceptMsg):
        if self.gossip_msg.is_leader(self.node_name):
            logger.warning("%s get accept request from %s, but i am the leader, ignore this accept",
                           self.verbose_name, msg_obj.from_node)
            return
        if not self.gossip_msg.is_leader(msg_obj.from_node):
            logger.warning("%s get accept request from %s, but its not my leader(%s), ignore this accept",
                           self.verbose_name, msg_obj.from_node, self.gossip_msg.get_leader())
            return
        if self.client_settings["ignore_accept"]:
            logger.info(f"ignore accept from {msg_obj.from_node}")
            return
        log_index, value = msg_obj.pos, msg_obj.value
        req_id = msg_obj.req_id
        resp = multi_paxos_msg.AcceptAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos(log_index)
        if msg_obj.prepare_pn < self.prepare_pn:
            logger.error("%s get a accept request with smaller prepare_pn %s from node %s, my pn %s, ignore this accept",
                         self.verbose_name, msg_obj.prepare_pn, msg_obj.from_node,
                         self.prepare_pn)
            return
        else:
            # here, we have msg_obj.prepare_pn == self.prepare_pn
            self.log_data_manager.mark_slot_accepted(self.prepare_pn, log_index, value, req_id)
            resp.set_state_success()
        await self.send_msg_queue.put((msg_obj.from_node, resp))
        return

    async def handle_accept_ack(self, msg: multi_paxos_msg.AcceptAckMsg):
        accept_ack_evt = self.accept_ack_evts.get(msg.pos, None)
        if not accept_ack_evt:
            return
        await accept_ack_evt.get_ack(msg, self.check_Q2_quorum)
        return

    async def background_batch_accept(self):
        while not self._stop:
            await curio.sleep(multi_paxos_msg.NODE_TIMEOUT + random.randint(1000, 2000) / 1000)
            if not self.gossip_msg.is_leader(self.node_name):
                continue
            logger.debug("background_batch_accept %s", self.retry_accept_data)
            if not self.retry_accept_data:
                continue
            msg = multi_paxos_msg.BatchAcceptMsg()
            msg.set_data(list(self.retry_accept_data.values()))
            msg.set_prepare_pn(self.prepare_pn)
            msg.set_from_node(self.node_name)
            for node_name in self.get_Q2_recipients():
                await self.send_msg_queue.put((node_name, msg))
        return

    async def handle_batch_accept(self, msg: multi_paxos_msg.BatchAcceptMsg):
        from_who = msg.from_node
        if not self.gossip_msg.is_leader(from_who):
            logger.warning("%s got a batch accept from %s, but it is not my leader(%s)",
                           self.log_data_manager, from_who, self.gossip_msg.get_leader())
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s got a batch accept from %s, but its pn (%s)is smaller then ours(%s)",
                           self.log_data_manager, from_who, msg.prepare_pn, self.prepare_pn)
            return
        if self.client_settings["ignore_accept"]:
            return
        pos_list = []
        for pos, value, req_id in msg.data:
            pos_list.append(pos)
            self.log_data_manager.mark_slot_accepted(msg.prepare_pn, pos, value, req_id)
        resp = multi_paxos_msg.BatchAcceptAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos_list(pos_list)
        await self.send_msg_queue.put((from_who, resp))
        return

    async def handle_batch_accept_ack(self, msg: multi_paxos_msg.BatchAcceptAckMsg):
        if not self.gossip_msg.is_leader(self.node_name):
            logger.warning("im not the leader(%s), but got a batch accept ack from %s",
                           self.gossip_msg.get_leader(), msg.from_node)
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("i(pn=%s) got a batch accept ack with smaller pn %s from %s",
                           self.prepare_pn, msg.prepare_pn, msg.from_node)
            return
        for pos in msg.pos_list:
            if pos not in self.accept_ack_evts:  # chosen
                continue
            ret = self.accept_ack_evts[pos].get_ack_sync(msg, self.check_Q2_quorum)
            if ret:
                log_data = self.log_data_manager.log_data[pos]
                del self.retry_accept_data[pos]
                del self.accept_ack_evts[pos]
                self.log_data_manager.mark_slot_chosen(self.prepare_pn, pos, log_data.value, log_data.req_id)
                for name in self.node_names:
                    self.chosen_broadcast_list[name][pos] = [pos, log_data.value, log_data.req_id]
        return

    async def background_batch_chosen(self):
        while not self._stop:
            st = multi_paxos_msg.NODE_TIMEOUT + random.randint(1000, 2000) / 1000
            await curio.sleep(st)
            if not self.gossip_msg.is_leader(self.node_name):
                continue
            logger.debug("background_batch_chosen %s", self.chosen_broadcast_list)
            for node_name, pos_datas in self.chosen_broadcast_list.items():
                if not pos_datas:
                    continue
                datas = list(pos_datas.values())
                msg = multi_paxos_msg.BatchChosenMsg()
                msg.set_from_node(self.node_name)
                msg.set_prepare_pn(self.prepare_pn)
                msg.set_data(datas)
                await self.send_msg_queue.put((node_name, msg))
        return

    async def handle_batch_chosen(self, msg: multi_paxos_msg.BatchChosenMsg):
        from_who = msg.from_node
        if not self.gossip_msg.is_leader(from_who):
            logger.warning("%s got a batch chosen from %s, but it is not my leader(%s)",
                           self.log_data_manager, from_who, self.gossip_msg.get_leader())
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s got a batch chosen from %s, but its pn (%s)is smaller then ours(%s)",
                           self.log_data_manager, from_who, msg.prepare_pn, self.prepare_pn)
            return
        if self.client_settings["ignore_accept"]:
            return
        pos_list = []
        for pos, value, req_id in msg.data:
            logger.debug(f"handle batch chosen {pos} {value} {req_id}")
            self.log_data_manager.mark_slot_chosen(msg.prepare_pn, pos, value, req_id)
            pos_list.append(pos)
        self.log_data_manager.log_index = max(self.log_data_manager.log_index, *pos_list)
        logger.debug(f"handle_batch_chosen {pos_list} {self.log_data_manager.all_chosen_index} {self.log_data_manager.log_index}")
        resp = multi_paxos_msg.BatchChosenAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos_list(pos_list)
        await self.send_msg_queue.put((from_who, resp))
        return

    async def handle_batch_chosen_ack(self, msg: multi_paxos_msg.BatchChosenAckMsg):
        if not self.gossip_msg.is_leader(self.node_name):
            logger.warning("im(%s) not the leader(%s), but got a batch chosen ack from %s",
                           self.verbose_name, self.gossip_msg.get_leader(), msg.from_node)
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s(pn=%s) got a batch chosen ack with smaller pn %s from %s",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn, msg.from_node)
            return
        logger.debug(f"get batch chosen ack from {msg.prepare_pn} {msg.from_node} {msg.pos_list}")
        from_node = msg.from_node
        for pos in msg.pos_list:
            del self.chosen_broadcast_list[from_node][pos]
        return

    async def handle_info(self, msg: multi_paxos_msg.ClientNodeInfoCmd):
        info_key = msg.info_key  # info_key is all for now
        resp = multi_paxos_msg.ClientNodeInfoResult()
        resp.set_from_node(self.node_name)
        if self.gossip_msg.is_leader(self.node_name):
            leader_cluster_state = self.cluster_state.name
        else:
            leader_cluster_state = self.gossip_msg.get_leader_cluster_state()
        info = {"leader": self.gossip_msg.get_leader(),
                "leader_online": self.gossip_msg.is_leader_online(),
                "cluster_state": self.cluster_state.name,
                "prepare_pn": self.prepare_pn,
                "nodes": {},
                "all_chosen_index": self.log_data_manager.all_chosen_index,
                "log_index": self.log_data_manager.log_index,
                "leader_cluster_state": leader_cluster_state,
                }
        nodes = {}
        for node_name in self.nodes_map:
            tmp = {"gossip": self.gossip_msg.infos[node_name]["gossip"].copy(),
                   "last_pong_time": self.gossip_msg.get_last_pong_time(node_name),
                   "online": self.gossip_msg.is_node_online(node_name),
                   }
            nodes[node_name] = tmp
        info["nodes"] = nodes
        resp.set_info(info)
        return resp.get_bytes()

    async def handle_learn(self, msg_obj: multi_paxos_msg.ClientLearnCMD):
        """
        client issue a learn request
        """
        req_id = msg_obj.req_id
        state = self.req_id_history.get(req_id, None)
        resp = multi_paxos_msg.ClientLearnResult()
        resp.set_state(state)
        return resp.get_bytes()

    async def handle_get_log_data(self, msg: multi_paxos_msg.ClientGetLogDataCMD):
        min_index, max_index = msg.min_index, msg.max_index
        data = self.log_data_manager.log_data[min_index: max_index+1]
        resp = multi_paxos_msg.ClientGetLogDataResult()
        resp.set_from_node(self.node_name)
        resp.set_log_data(data)
        return resp.get_bytes()

    async def handle_disable_leadership(self, msg: multi_paxos_msg.ClientDisableLeadershipCMD):
        if msg.flag == 1:
            self.client_settings["never_attempt_to_acquire_leadership"] = True
        else:
            self.client_settings["never_attempt_to_acquire_leadership"] = False
        logger.info(f"never_attempt_to_acquire_leadership {msg.flag}")
        resp = multi_paxos_msg.ClientDisableLeadershipResult()
        resp.set_from_node(self.node_name)
        return resp.get_bytes()

    async def handle_ignore_accept_msg(self, msg: multi_paxos_msg.ClientIgnoreAcceptCMD):
        self.client_settings["ignore_accept"] = True if msg.flag == 1 else False
        logger.info(f"ignore accept {msg.flag}")
        resp = multi_paxos_msg.ClientIgnoreAcceptAck()
        resp.set_from_node(self.node_name)
        return resp.get_bytes()

    async def handle_disable_pong(self, msg: multi_paxos_msg.ClientDisablePongCMD):
        self.client_settings["disable_pong"] = True if msg.flag == 1 else False
        logger.info(f"disable_pong {msg.flag}")
        resp = multi_paxos_msg.ClientDisablePongAck()
        resp.set_from_node(self.node_name)
        return resp.get_bytes()

    async def handle_get_retry_accept_list(self, msg: multi_paxos_msg.ClientGetRetryAcceptListCMD):
        resp = multi_paxos_msg.ClientGetRetryAcceptListAck()
        resp.set_data(self.retry_accept_data)
        resp.set_from_node(self.node_name)
        return resp.get_bytes()

    def run(self):
        logger.info("%s Running" % self.verbose_name)
        try:
            run(self.io_server)
        except KeyboardInterrupt:
            self._stop = True
        logger.info("%s return" % self.verbose_name)
        return


def run_machines():
    # test_majority()
    node_id = int(sys.argv[1])
    conf = Config()
    machine = LogStateMatchine(node_id, conf)
    machine.run()
    return


def main():
    run_machines()
    return


if __name__ == "__main__":
    main()


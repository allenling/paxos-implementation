"""
"""
import enum
import sys
import threading
import json
import time
import logging
import random
from enum import Enum
import curio
from curio import run, spawn
from curio.socket import *
from typing import Mapping, Sequence

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s.%(msecs)03d] %(process)d:%(thread)d %(levelname)s [%(filename)s.%(funcName)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("multi-paxos")

class MsgType(Enum):
    PING = 0
    PREPARE = 1
    ACCEPT = 2
    PREPARE_ACK = 3
    ACCEPT_ACK = 4
    PONG = 5
    CLIENT = 6
    BATCH_ACCEPT = 7
    BATCH_ACCPET_ACK = 8
    BATCH_CHOSEN = 9
    BATCH_CHOSEN_ACK = 10
    PREPARE_SYNC = 11
    PREPARE_SYNC_ACK = 12


class MsgStatus(Enum):
    SUC = 0
    FAIL = 1
    TIMEOUT = 2

IOMSG_FIX_LEN = 1000

class IOMsg:
    from_node = None
    itype = None
    timestamp = None

    def set_from_node(self, from_node):
        self.from_node = from_node
        return

    def __str__(self):
        return "IOMsg<%s>" % self.itype

    def __repr__(self):
        return self.__str__()

    def get_data(self):
        raise NotImplementedError

    @classmethod
    def from_json(cls, jdata):
        obj = cls._from_json(jdata["data"])
        obj.timestamp = jdata["timestamp"]
        obj.itype = MsgType(jdata["itype"])
        obj.set_from_node(jdata["from_node"])
        return obj

    @classmethod
    def _from_json(cls, jdata):
        raise NotImplementedError

    def get_bytes(self):
        res = {}
        data = self.get_data()
        res["itype"] = self.itype.value
        res["from_node"] = self.from_node
        res["timestamp"] = time.time()
        res["data"] = data
        s = json.dumps(res)
        s = s.zfill(IOMSG_FIX_LEN)
        return s.encode()


class GossipMsg:
    OFFLINE = "offline"
    ONLINE = "online"

    def __init__(self, node_names, myself):
        self.myself = myself
        self.leader = None
        self.leader_prepare_pn = -1
        self.prepare_pn = -1
        template = {"status": self.OFFLINE,
                    "last_ping_time": -1, "sock": None,
                    "last_pong_time": float("inf"),
                    "gossip": {"leader": None, "leader_online": False, "leader_prepare_pn": -1, "prepare_pn": -1},
                    }
        self.infos = {name: template.copy() for name in node_names}
        return

    def set_prepare_pn(self, parepare_pn):
        self.prepare_pn = parepare_pn
        return

    def set_leader(self, node_name):
        self.leader = node_name
        return

    def set_leader_online(self):
        if not self.leader:
            return
        self.infos[self.leader]["status"] = self.ONLINE
        return

    def get_leader(self):
        return self.leader

    def is_leader_online(self):
        if self.leader:
            if self.myself == self.leader:
                return True
            return self.infos[self.leader]["sock"] is not None and self.infos[self.leader]["status"] == self.ONLINE
        return False

    def is_leader_offline(self):
        return not self.is_leader_online()

    def am_i_leader(self, node_name):
        return self.leader is not None and self.leader == node_name

    def is_node_offline(self, node_name):
        return self.infos[node_name]["sock"] is None or self.infos[node_name]["status"] == self.OFFLINE

    def is_node_online(self, node_name):
        return self.infos[node_name]["sock"] is not None and self.infos[node_name]["status"] == self.ONLINE

    def update_node_last_ping_time(self, node_name):
        self.infos[node_name]["last_ping_time"] = time.time()
        return

    def update_node_last_pong_time(self, node_name):
        self.infos[node_name]["last_pong_time"] = time.time()
        return

    def set_node_sock(self, node_name, sock):
        self.infos[node_name]["sock"] = sock
        return

    def get_last_ping_time(self, node_name):
        return self.infos[node_name]["last_pong_time"]

    def get_last_pong_time(self, node_name):
        return self.infos[node_name]["last_pong_time"]

    def get_node_prepare_pn(self, node_name):
        return self.infos[node_name]["gossip"]["prepare_pn"]

    def get_node_sock(self, node_name):
        return self.infos[node_name]["sock"]

    def set_node_online(self, node_name, gossip):
        self.infos[node_name]["status"] = self.ONLINE
        self.infos[node_name]["gossip"] = gossip.copy()
        return

    def set_node_offline(self, node_name):
        self.infos[node_name]["status"] = self.OFFLINE
        return

    def get_online_nodes(self):
        res = []
        for node_name, info in self.infos.items():
            node_gossip_info = self.infos[node_name]["gossip"]
            if self.is_node_online(node_name) and node_gossip_info["prepare_pn"] >= self.prepare_pn:
                # someone is online and can see a leader
                res.append([node_name, node_gossip_info])
        res = sorted(res, key=lambda n: n[1]["prepare_pn"])
        return res

    def update_nodes_status(self):
        now_time = time.time()
        for node_name, info in self.infos.items():
            if info["sock"] and info["last_pong_time"] - now_time < NODE_TIMEOUT * 2:
                info["status"] = self.ONLINE
            else:
                info["status"] = self.OFFLINE
        online_nodes = self.get_online_nodes()
        if self.leader and any([self.leader == i[1]["leader"] for i in online_nodes]):
            self.infos[self.leader]["status"] = self.ONLINE
        return online_nodes

class PingPongMsg:

    def __init__(self):
        self.leader = None
        self.leader_online = None
        self.leader_prepare_pn = None
        self.prepare_pn = None
        self.all_chosen_index = None
        return

    def get_data(self):
        return {"leader": self.leader, "leader_online": self.leader_online, "prepare_pn": self.prepare_pn,
                "all_chosen_index": self.all_chosen_index, "leader_prepare_pn": self.leader_prepare_pn}

    @classmethod
    def from_gossip_msg(cls, gossip_msg_obj: GossipMsg, machine):
        msg = cls()
        msg.leader = gossip_msg_obj.leader
        msg.leader_online = gossip_msg_obj.is_leader_online()
        msg.leader_prepare_pn = gossip_msg_obj.leader_prepare_pn
        msg.prepare_pn = machine.prepare_pn
        msg.all_chosen_index = machine.log_data_manager.all_chosen_index
        return msg

    @classmethod
    def _from_json(cls, jdata):
        msg = cls()
        msg.leader = jdata["leader"]
        msg.leader_online = jdata["leader_online"]
        msg.prepare_pn = jdata["prepare_pn"]
        msg.all_chosen_index = jdata["all_chosen_index"]
        msg.leader_prepare_pn = jdata["leader_prepare_pn"]
        return msg


class PinigMsg(PingPongMsg, IOMsg):
    itype = MsgType.PING


class PongMsg(PingPongMsg, IOMsg):
    itype = MsgType.PONG


class PrepareMsg(IOMsg):
    itype = MsgType.PREPARE

    def __init__(self, prepare_pn):
        self.prepare_pn = prepare_pn
        return

    def set_pn(self, pn):
        self.prepare_pn = pn
        return

    def get_data(self):
        return {"prepare_pn": self.prepare_pn}

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareMsg(jdata["prepare_pn"])
        return msg


class PrepareACKMsg(IOMsg):
    itype = MsgType.PREPARE_ACK

    def __init__(self):
        self.prepare_pn = None
        self.all_chosen_index = None
        self.log_index = None
        self.state = None
        return

    def is_fail(self):
        return self.state == MsgStatus.FAIL

    def is_success(self):
        return self.state == MsgStatus.SUC

    def set_status_success(self):
        self.state = MsgStatus.SUC
        return

    def set_status_fail(self):
        self.state = MsgStatus.FAIL
        return

    def is_suc(self):
        return self.state == MsgStatus.SUC

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_all_chosen_index(self, index):
        self.all_chosen_index = index
        return

    def set_log_index(self, log_index):
        self.log_index = log_index
        return

    def get_data(self):
        return {"state": self.state.value, "prepare_pn": self.prepare_pn,
                "all_chosen_index": self.all_chosen_index, "log_index": self.log_index,
                }

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareACKMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.state = MsgStatus(jdata["state"])
        msg.all_chosen_index = jdata["all_chosen_index"]
        msg.log_index = jdata["log_index"]
        return msg


class PrepareSyncMsg(IOMsg):
    itype = MsgType.PREPARE_SYNC

    def __init__(self):
        self.min_index = None
        self.max_index = None
        self.prepare_pn = None
        return

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_min_index(self, min_index):
        self.min_index = min_index
        return

    def set_max_index(self, max_index):
        self.max_index = max_index
        return

    def get_data(self):
        return {"prepare_pn": self.prepare_pn,
                "min_index": self.min_index, "max_index": self.max_index,
                }

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareSyncMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.min_index = jdata["min_index"]
        msg.max_index = jdata["max_index"]
        return msg


class PrepareSyncACKMsg(IOMsg):
    itype = MsgType.PREPARE_SYNC_ACK

    def __init__(self):
        self.state = None
        self.prepare_pn = None
        self.min_index = None
        self.max_index = None
        self.sync_data = []  # sync_data=[LogData, ], sync_data contains all values from all_chosen_index to log_index
        return

    def is_fail(self):
        return self.state == MsgStatus.FAIL

    def is_success(self):
        return self.state == MsgStatus.SUC

    def set_status_success(self):
        self.state = MsgStatus.SUC
        return

    def set_status_fail(self):
        self.state = MsgStatus.FAIL
        return

    def is_suc(self):
        return self.state == MsgStatus.SUC

    def set_prepare_pn(self, prepare_pn):
        self.prepare_pn = prepare_pn
        return

    def set_sync_data(self, sync_data):
        self.sync_data = sync_data.copy()
        return

    def set_min_max_index(self, min_index, max_index):
        self.min_index = min_index
        self.max_index = max_index
        return

    def get_data(self):
        return {"state": self.state.value, "prepare_pn": self.prepare_pn,
                "sync_data": [(i.pos, i.value, i.req_id, i.state.value, i.prepare_pn) for i in self.sync_data],
                "min_index": self.min_index, "max_index": self.max_index,
                }

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareSyncACKMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.state = MsgStatus(jdata["state"])
        msg.sync_data = [LogData(i[0], i[1], i[2], LogDataState(i[3]), i[4]) for i in jdata["sync_data"]]
        msg.min_index = jdata["min_index"]
        msg.max_index = jdata["max_index"]
        return msg


class AcceptMsg(IOMsg):
    itype = MsgType.ACCEPT

    def __init__(self):
        self.prepare_pn = None
        self.pos = None
        self.value = None
        self.req_id = None
        return

    def set_prepare_pn(self, prepare_pn):
        self.prepare_pn = prepare_pn
        return

    def set_pos_and_value(self, pos, value):
        self.pos, self.value = pos, value
        return

    def set_req_id(self, req_id):
        self.req_id = req_id
        return

    def get_data(self):
        return {"value": self.value, "prepare_pn": self.prepare_pn,
                "pos": self.pos, "req_id": self.req_id}

    @classmethod
    def _from_json(cls, jdata):
        msg = AcceptMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.pos = jdata["pos"]
        msg.value = jdata["value"]
        msg.req_id = jdata["req_id"]
        return msg


class AcceptAckMsg(IOMsg):
    itype = MsgType.ACCEPT_ACK

    def __init__(self):
        self.prepare_pn = None
        self.state = None
        self.pos = None
        return

    def is_fail(self):
        return self.state == MsgStatus.FAIL

    def is_success(self):
        return self.state == MsgStatus.SUC

    def is_suc(self):
        return self.is_success()

    def set_state_success(self):
        self.state = MsgStatus.SUC
        return

    def set_state_fail(self):
        self.state = MsgStatus.FAIL
        return

    def set_pos(self, pos):
        self.pos = pos
        return

    def set_prepare_pn(self, prepare_pn):
        self.prepare_pn = prepare_pn
        return

    def get_data(self):
        return {"state": self.state.value, "prepare_pn": self.prepare_pn,
                "pos": self.pos}

    @classmethod
    def _from_json(cls, jdata):
        msg = AcceptAckMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.state = MsgStatus(jdata["state"])
        msg.pos = jdata["pos"]
        return msg


class BatchAcceptMsg(IOMsg):
    itype = MsgType.BATCH_ACCEPT
    prepare_pn = None
    data = []

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_data(self, data):
        self.data = data.copy()
        return

    def get_data(self):
        return {"data": self.data, "prepare_pn": self.prepare_pn}

    @classmethod
    def _from_json(cls, jdata):
        msg = BatchAcceptMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.data = jdata["data"].copy()
        return msg


class BatchAcceptAckMsg(IOMsg):
    itype = MsgType.BATCH_ACCPET_ACK
    prepare_pn = None
    pos_list = []

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_pos_list(self, pos_list):
        self.pos_list = pos_list.copy()
        return

    def get_data(self):
        return {"pos_list": self.pos_list}

    @classmethod
    def _from_json(cls, jdata):
        msg = BatchAcceptAckMsg()
        msg.pos_list = jdata["pos_list"].copy()
        msg.prepare_pn = jdata["prepare_pn"]
        return msg


class BatchChosenMsg(IOMsg):
    itype = MsgType.BATCH_CHOSEN
    prepare_pn = None
    data = []

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_data(self, data):
        self.data = data.copy()
        return

    def get_data(self):
        return {"data": self.data, "prepare_pn": self.prepare_pn}

    @classmethod
    def _from_json(cls, jdata):
        msg = BatchChosenMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.data = jdata["data"].copy()
        return msg


class BatchChosenAckMsg(IOMsg):
    itype = MsgType.BATCH_CHOSEN_ACK
    prepare_pn = None
    pos_list = []

    def set_prepare_pn(self, pn):
        self.prepare_pn = pn
        return

    def set_pos_list(self, pos_list):
        self.pos_list = pos_list.copy()
        return

    def get_data(self):
        return {"pos_list": self.pos_list, "prepare_pn": self.prepare_pn}

    @classmethod
    def _from_json(cls, jdata):
        msg = BatchChosenAckMsg()
        msg.pos_list = jdata["pos_list"].copy()
        msg.prepare_pn = jdata["prepare_pn"]
        return msg


class ClientCMDType(enum.Enum):
    CHOOSE = 0
    CHOOSE_RESULT = 1
    INFO = 2
    INFO_RESILT = 3
    LEARN = 4
    LEARN_RESULT = 5
    GET_LOG_DATA = 6
    GET_LOG_DATA_RESULT = 7
    DISABLE_LEADERSHIP = 8
    DISABLE_LEADERSHIP_RESULT = 9


class ClientMsg(IOMsg):
    """
    {timestamp: 111, itype: MsgType.CLIENT, from_node: client_id,
     data: {..., cmd_type: ctype, ...},
     }
    """
    itype = MsgType.CLIENT
    cmd_type = None

    def __str__(self):
        return "ClientMsg<%s>" % self.cmd_type

    def __repr__(self):
        return self.__str__()

    def get_data(self):
        data = self.get_cmd_data()
        data["cmd_type"] = self.cmd_type.value
        return data

    def get_cmd_data(self):
        raise NotImplementedError

    @classmethod
    def _from_json(cls, jdata):
        obj = cls._cmd_from_json(jdata)
        return obj

    @classmethod
    def _cmd_from_json(cls, jdata):
        raise NotImplementedError


class ClientChooseCmd(ClientMsg):
    cmd_type = ClientCMDType.CHOOSE
    value = None
    req_id = None

    def set_value(self, value):
        self.value = value
        return

    def set_req_id(self, req_id):
        self.req_id = req_id
        return

    def get_cmd_data(self):
        return {"value": self.value, "req_id": self.req_id}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientChooseCmd()
        obj.value = jdata["value"]
        obj.req_id = jdata["req_id"]
        return obj

class ChooseState(enum.Enum):
    suc = 0
    fail = 1
    timeout = 2


class ClientChooseResult(ClientMsg):
    cmd_type = ClientCMDType.CHOOSE_RESULT
    state = None
    reason = None

    def set_status_success(self):
        self.state = ChooseState.suc
        return

    def set_status_fail(self):
        self.state = ChooseState.fail
        return

    def set_status_timeout(self):
        self.state = ChooseState.timeout
        return

    def set_reason(self, reason):
        self.reason = reason
        return

    def get_cmd_data(self):
        return {"state": self.state.value, "reason": self.reason}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientChooseResult()
        obj.state = ChooseState(jdata["state"])
        obj.reason = jdata["reason"]
        return obj


class ClientNodeInfoCmd(ClientMsg):
    cmd_type = ClientCMDType.INFO
    info_key = "all"

    def set_info_key(self, info_key):
        self.info_key = info_key
        return

    def get_cmd_data(self):
        return {"info_key": self.info_key}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientNodeInfoCmd()
        obj.info_key = jdata["info_key"]
        return obj


class ClientNodeInfoResult(ClientMsg):
    cmd_type = ClientCMDType.INFO_RESILT
    info = {}

    def set_info(self, info):
        self.info = info.copy()
        return

    def get_cmd_data(self):
        return {"info": self.info.copy()}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientNodeInfoResult()
        obj.info = jdata["info"].copy()
        return obj


class LearnState(enum.Enum):
    not_found = 0
    suc = 1
    fail = 2
    timeout = 3


class ClientLearnCMD(ClientMsg):
    cmd_type = ClientCMDType.LEARN
    req_id = None

    def set_req_id(self, req_id):
        self.req_id = req_id
        return

    def get_cmd_data(self):
        return {"req_id": self.req_id}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientLearnCMD()
        obj.req_id = jdata["req_id"]
        return obj


class ClientLearnResult(ClientMsg):
    cmd_type = ClientCMDType.LEARN_RESULT
    state = None
    pos = None
    value = None

    def set_state(self, s):
        self.state = s
        return

    def set_pos(self, pos):
        self.pos = pos
        return

    def set_value(self, value):
        self.value = value
        return

    def get_cmd_data(self):
        return {"state": self.state.value, "pos": self.pos,
                "value": self.value}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientLearnResult()
        obj.state = jdata["state"]
        obj.pos = jdata["pos"]
        obj.value = jdata["value"]
        return obj


class ClientGetLogDataCMD(ClientMsg):
    cmd_type = ClientCMDType.GET_LOG_DATA
    min_index = 0
    max_index = 0

    def set_index(self, min_index, max_index):
        self.min_index = min_index
        self.max_index = max_index
        return

    def get_cmd_data(self):
        return {"min_index": self.min_index, "max_index": self.max_index}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientGetLogDataCMD()
        obj.min_index = jdata["min_index"]
        obj.max_index = jdata["max_index"]
        return obj


class ClientGetLogDataResult(ClientMsg):
    cmd_type = ClientCMDType.GET_LOG_DATA_RESULT
    log_data_list = []

    def set_log_data(self, log_data_list):
        self.log_data_list = sorted(log_data_list, key=lambda n: n.pos)
        return

    def get_cmd_data(self):
        return {"log_data": [i.to_dict() for i in self.log_data_list]}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientGetLogDataCMD()
        obj.log_data_list = jdata["log_data_list"]
        return obj


class ClientDisableLeadershipCMD(ClientMsg):
    cmd_type = ClientCMDType.DISABLE_LEADERSHIP
    flag = 0

    def set_flag(self, flag):
        self.flag = flag
        return

    def get_cmd_data(self):
        return {"flag": self.flag}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientDisableLeadershipCMD()
        obj.flag = jdata["flag"]
        return obj


class ClientDisableLeadershipResult(ClientMsg):
    cmd_type = ClientCMDType.DISABLE_LEADERSHIP_RESULT

    def get_cmd_data(self):
        return {}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientDisableLeadershipResult()
        return obj


MSG_TYPE_CLASS_MAP = {MsgType.PING: PinigMsg,
                      MsgType.PONG: PongMsg,
                      MsgType.PREPARE: PrepareMsg,
                      MsgType.PREPARE_ACK: PrepareACKMsg,
                      MsgType.ACCEPT: AcceptMsg,
                      MsgType.ACCEPT_ACK: AcceptAckMsg,
                      MsgType.PREPARE_SYNC_ACK: PrepareSyncACKMsg,
                      MsgType.PREPARE_SYNC: PrepareSyncMsg,
                      MsgType.BATCH_ACCEPT: BatchAcceptMsg,
                      MsgType.BATCH_ACCPET_ACK: BatchAcceptAckMsg,
                      MsgType.BATCH_CHOSEN: BatchChosenMsg,
                      MsgType.BATCH_CHOSEN_ACK: BatchChosenAckMsg,
                      }

CMD_TYPE_CLASS_MAP = {ClientCMDType.CHOOSE: ClientChooseCmd,
                      ClientCMDType.INFO: ClientNodeInfoCmd,
                      ClientCMDType.GET_LOG_DATA: ClientGetLogDataCMD,
                      ClientCMDType.DISABLE_LEADERSHIP: ClientDisableLeadershipCMD,
                      }

def get_msg_obj_from_json(jdata):
    itype = MsgType(jdata["itype"])
    if itype == MsgType.CLIENT:
        client_cmd_class = CMD_TYPE_CLASS_MAP[ClientCMDType(jdata["data"]["cmd_type"])]
        obj = client_cmd_class.from_json(jdata)
    else:
        msg_class = MSG_TYPE_CLASS_MAP[itype]
        obj = msg_class.from_json(jdata)
    return obj


NODE_TIMEOUT = 10  # seconds


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


class MajorityAckEvt:
    allowed_type = [MsgType.PREPARE_ACK, MsgType.ACCEPT_ACK, MsgType.PREPARE_SYNC_ACK]

    def __init__(self, pn, half, resp_type=MsgType.PREPARE_ACK):
        assert resp_type in self.allowed_type
        self.target_count = half
        self.pn = pn
        self.evt = curio.Event()
        self.ack_msgs = []
        self.status = None
        self.resp_type = resp_type
        return

    async def wait(self):
        try:
            result = await curio.timeout_after(NODE_TIMEOUT, self.evt.wait)
        except curio.TaskTimeout:
            self.status = MsgStatus.TIMEOUT
        else:
            self.status = MsgStatus.SUC
        return

    def is_suc(self):
        return self.status and self.status == MsgStatus.SUC

    async def get_ack(self, ack_msg):
        if ack_msg.itype != self.resp_type:
            logger.error("MajorityAckEvt(%s) get ack msg(%s)", ack_msg.itype, self.resp_type)
            return
        logger.debug("MajorityAckEvt(%s) get ack msg from node %s, pn %s, status %s, and my pn %s, my target count=%s",
                     self.resp_type, ack_msg.from_node,
                     ack_msg.prepare_pn,
                     ack_msg.state,
                     self.pn,
                     self.target_count
                     )
        if ack_msg.prepare_pn != self.pn:
            return
        if self.status is not None or self.evt.is_set():
            return
        self.ack_msgs.append(ack_msg)
        if self.target_count > 0 and ack_msg.is_suc():
            self.target_count -= 1
            logger.debug("MajorityAckEvt.get_ack current target_count %s", self.target_count)
            if self.target_count == 0:
                await self.evt.set()
        return

    def get_max_prepare_ack_pn(self):
        return max([i.prepare_pn for i in self.ack_msgs], default=self.pn)

    def get_fail_nodes(self):
        fail_nodes = [msg.from_node for msg in self.ack_msgs if msg.is_fail()]
        return fail_nodes

    def get_all_success_msgs(self):
        msgs = [msg for msg in self.ack_msgs if msg.is_suc()]
        return msgs


class ClusterState(enum.Enum):
    healthy = 0
    unhealthy = 1
    idle = 2


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
        return "LogData<%s, %s, %s, %s, %s>" % (self.pos, self.value, self.req_id, self.state, self.prepare_pn,)

    def __repr__(self):
        return self.__str__()

    def to_tuple(self):
        return self.pos, self.value, self.req_id, self.state.value, self.prepare_pn

    def to_dict(self):
        return {"pos": self.pos, "value": self.value, "req_id": self.req_id,
                "state": self.state.value, "prepare_pn": self.prepare_pn,
                }


class ReqidInfo:

    def __init__(self, req_id, pos, state:LearnState):
        self.req_id = req_id
        self.pos = pos
        self.state = state
        return


class LogDataManager:

    def __init__(self, nodes, half):
        self.half = half
        self.log_data: Sequence[LogData] = [LogData(i) for i in range(100)]
        self.retry_accept_data = {}  # {pos: (value, req_id, ack_nodes: set()}
        self.chosen_broadcast: Mapping[int: Mapping[int, LogData]] = {node_name: {} for node_name in nodes}
        self.batch_accept_ack_evt = None
        self.req_id_history: Mapping[str, ReqidInfo] = {}
        self.all_chosen_index = None  # all value whose index is less then or equal to all_chosen_index are on chosen state
        self.log_index = -1
        return

    def get_next_log_index(self):
        self.log_index += 1
        if self.log_index >= len(self.log_data) * 2 // 3:
            self.log_data.extend([None]*len(self.log_data))
        return self.log_index

    def update_all_chosen_index(self, current_chosen_index):
        my_chosen_index = self.all_chosen_index or -1
        if self.log_data[my_chosen_index + 1].state != LogDataState.chosen:
            return
        self.all_chosen_index = my_chosen_index + 1
        while self.all_chosen_index < self.log_index:
            next_index = self.all_chosen_index + 1
            if self.log_data[next_index] is None or self.log_data[next_index].state != LogDataState.chosen:
                break
            self.all_chosen_index += 1
        return

    def update_chosen_broadcast(self, node_name, pos, log_data: LogData):
        if pos not in self.chosen_broadcast[node_name]:
            self.chosen_broadcast[node_name][pos] = log_data
        return

    def add_chosen(self, prepare_pn, pos, value, req_id):
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.chosen, prepare_pn)
        self.req_id_history[req_id] = ReqidInfo(req_id, pos, LearnState.suc)
        self.update_all_chosen_index(pos)
        return

    def mark_slot_chosen(self, prepare_pn, pos, value, req_id):
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.chosen, prepare_pn)
        self.req_id_history[req_id] = ReqidInfo(req_id, pos, LearnState.suc)
        self.update_all_chosen_index(pos)
        return

    def mark_slot_accepted(self, prepare_pn, pos, value, req_id):
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.accpeted, prepare_pn)
        self.log_index = max(self.log_index, pos)
        return

    def may_need_to_sync_chosen(self, node_name, node_all_chosen_index):
        if self.all_chosen_index is None:
            return
        if node_all_chosen_index is None or self.all_chosen_index > node_all_chosen_index:
            node_all_chosen_index = node_all_chosen_index or 0
            for pos in range(node_all_chosen_index, self.all_chosen_index+1):
                self.update_chosen_broadcast(node_name, pos, self.log_data[pos])
        elif self.all_chosen_index == node_all_chosen_index and self.chosen_broadcast[node_name]:
            self.chosen_broadcast[node_name] = {}
        return

    def mark_timeout_and_need_retry(self, prepare_pn, pos, value, req_id):
        self.retry_accept_data[pos] = {"value": value, "req_id": req_id, "ack_nodes": set()}
        self.log_data[pos] = LogData(pos, value, req_id, LogDataState.timeout, prepare_pn)
        self.req_id_history[req_id] = ReqidInfo(pos, req_id, LearnState.timeout)
        return

    def get_retry_accept_list(self):
        return self.retry_accept_data

    def get_chosen_broadcast_list(self):
        data = {}  # data={node_name: [(pos1, value1, req_id1), ...], ...}
        for node_name, value in self.chosen_broadcast.items():
            tmp = []
            if not value:
                continue
            for pos, log_data in value.items():
                tmp.append((pos, log_data.value, log_data.req_id))
            data[node_name] = tmp
        return data

    def update_from_batch_chosen_ack(self, msg: BatchChosenAckMsg):
        node_name = msg.from_node
        for pos in msg.pos_list:
            del self.chosen_broadcast[node_name][pos]
        return

    def update_from_batch_accept_ack(self, prepare_pn, msg: BatchAcceptAckMsg):
        for pos in msg.pos_list:
            if self.log_data[pos].state == LogDataState.chosen:
                continue
            self.retry_accept_data[pos]["ack_nodes"].add(msg.from_node)
            if len(self.retry_accept_data[pos]["ack_nodes"]) == self.half:
                self.mark_slot_chosen(prepare_pn, pos)
                del self.retry_accept_data[pos]
        return

    def sync_prepare_data(self, prepare_pn, msgs: Sequence[PrepareSyncACKMsg]):
        min_index, max_index = msgs[0].min_index, msgs[0].max_index
        if max_index == -1:
            logger.info("no need to sync prepare data, now is setup stage")
            return
        if min_index == max_index:
            logger.info("no data need to be sync in preparation phrase")
            return
        my_sync_data: Sequence[LogData] = self.log_data[min_index: max_index + 1]
        datas: Sequence[Sequence[LogData]] = []
        for i in msgs:
            datas.append(i.sync_data)
        datas.append(my_sync_data)
        res = []
        for i in range(len(datas[0])):
            prepare_datas = [j[i] for j in datas]
            prepare_datas = sorted(prepare_datas, key=lambda n: -n.prepare_pn)
            chosen = LogData(prepare_datas[0].pos, value="no_op", req_id=None, state=LogDataState.chosen, prepare_pn=prepare_pn)
            for k in prepare_datas:
                if k.state == LogDataState.empty:
                    continue
                chosen.value = k.value
                chosen.req_id = k.req_id
                break
            res.append(chosen)
        for i in res:
            self.log_data[i.pos] = i
            if i.req_id:
                self.req_id_history[i.req_id] = ReqidInfo(i.req_id, i.pos, LearnState.suc)
        self.log_index = max_index
        self.update_all_chosen_index(min_index)
        # reset chosen_broadcast and retry_accept_data
        # chosen data will be updated in pong msg
        self.chosen_broadcast = {node_name: {} for node_name in self.chosen_broadcast}
        self.retry_accept_data = {}
        return

    def get_req_id_state(self, req_id):
        # for leader, return timeout or suc
        # if return not_found, that means new leader has lost such req_id
        state_info = self.req_id_history.get(req_id, None)
        if not state_info:
            return LearnState.not_found
        return state_info.state


class LogStateMatchine:

    def __init__(self, my_id, nodes_map):
        self.node_name = my_id
        self.verbose_name = "Machine<%s>" % my_id
        self.addr = nodes_map[self.node_name]
        self.nodes_map = {node_name: addr for node_name, addr in nodes_map.items() if node_name != my_id}  # {name: (address, port), ..}
        self.url_to_node_map = {url: name for name, url in self.nodes_map.items()}
        self.background_io_th = threading.Thread(target=self.io_server, daemon=True)
        self.gossip_msg = GossipMsg(nodes_map, my_id)
        self.handler_map = {MsgType.PING: self.handle_ping,
                            MsgType.PONG: self.handle_pong,
                            MsgType.PREPARE: self.handle_prepare,
                            MsgType.PREPARE_ACK: self.handle_prepare_ack,
                            MsgType.ACCEPT: self.handle_accept,
                            MsgType.ACCEPT_ACK: self.handle_accept_ack,
                            MsgType.PREPARE_SYNC: self.handle_prepare_sync,
                            MsgType.PREPARE_SYNC_ACK: self.handle_prepare_sync_ack,
                            MsgType.BATCH_ACCEPT: self.handle_batch_accept,
                            MsgType.BATCH_ACCPET_ACK: self.handle_batch_accept_ack,
                            MsgType.BATCH_CHOSEN: self.handle_batch_chosen,
                            MsgType.BATCH_CHOSEN_ACK: self.handle_batch_chosen_ack,
                            }
        self.client_hanlder_map = {ClientCMDType.CHOOSE: self.handle_choose,
                                   ClientCMDType.INFO: self.handle_info,
                                   ClientCMDType.GET_LOG_DATA: self.handle_get_log_data,
                                   ClientCMDType.DISABLE_LEADERSHIP: self.handle_disable_leadership,
                                   }
        self.cluster_state = ClusterState.unhealthy
        self._stop = False
        self.half = len(nodes_map) // 2
        self.election_delay_ms = -1
        self.prepare_pn = -1
        self.accepted_pn = -1
        self.accepted_value = None
        self.log_data_manager = LogDataManager(self.nodes_map, self.half)
        self.last_prepare_time = 0
        self.prepare_ack_evt = None
        self.prepare_sync_ack_evt = None
        self.accept_ack_evts = {}
        self.pn_yielder = disjoint_yielder(my_id)
        self.send_msg_queue = curio.Queue()
        self.never_attempt_to_acquire_leadership = False
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
            while True:
                client, addr = await sock.accept()
                await spawn(self.recv_from_node, client, addr, daemon=True)
        logger.info("%s io Server return" % self.verbose_name)
        return

    async def recv_from_node(self, client, addr):
        logger.info("%s recv_from_node from %s" % (self.verbose_name, addr))
        node_name = None
        client_name = None
        async with client:
            while True:
                try:
                    data_bytes = await client.recv(IOMSG_FIX_LEN)
                except Exception as e:
                    logger.error("%s handler client %s recv error %s", self.verbose_name, addr, str(e))
                    if node_name:
                        self.gossip_msg.set_node_sock(node_name, None)
                        if node_name < self.node_name:
                            await spawn(self.connect_to_node, node_name, daemon=True)
                    if client_name:
                        logger.warning("client %s close connection" % client_name)
                    await client.close()
                    return
                if not data_bytes:
                    logger.warning("%s handler client %s recv empty! means it close, node %s!", self.verbose_name, addr, node_name)
                    if node_name:
                        self.gossip_msg.set_node_sock(node_name, None)
                        if node_name < self.node_name:
                            await spawn(self.connect_to_node, node_name, daemon=True)
                    if client_name:
                        logger.warning("client %s close connection" % client_name)
                    await client.close()
                    return
                data = data_bytes.decode().strip("0")
                logger.debug("recv data %s", data)
                jdata = json.loads(data)
                msg_obj = get_msg_obj_from_json(jdata)
                node_name = msg_obj.from_node
                if msg_obj.itype == MsgType.CLIENT:
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
        while not self._stop:
            node_name, msg = await self.send_msg_queue.get()
            try:
                sock = self.gossip_msg.get_node_sock(node_name)
                logger.debug("%s is sending msg(%s) to node %s", self.verbose_name, msg.itype, node_name)
                if not sock:
                    logger.warning("%s have None sock for node %s, sending terminated", self.verbose_name, node_name)
                    continue
                await sock.sendall(msg.get_bytes())
            except Exception as e:
                logger.error("%s send node %s msg %s error", self.verbose_name, node_name, msg, exc_info=True)
                await sock.close()
        return

    async def connect_to_node(self, node_name):
        logger.info("%s start to connect to %s", self.verbose_name, node_name)
        sock = socket(AF_INET, SOCK_STREAM)
        node_url = self.nodes_map[node_name]
        while True:
            try:
                await sock.connect(node_url)
            except Exception as e:
                random_retry_ms = random.randint(1000, 2000)
                logger.info("%s connect to node<%s> fail, retry after %s(ms)", self.verbose_name, node_name, random_retry_ms, exc_info=True)
                await curio.sleep(random_retry_ms / 1000)
                continue
            break
        logger.info("%s connected to %s" % (self.verbose_name, node_name))
        self.gossip_msg.set_node_sock(node_name, sock)
        await spawn(self.recv_from_node, sock, node_url, daemon=True)
        return

    async def send_node_pong(self, node_name):
        while not self._stop:
            await curio.sleep(NODE_TIMEOUT // 2 + random.randint(100, 500) / 1000)
            pong_msg = PongMsg.from_gossip_msg(self.gossip_msg, self)
            pong_msg.set_from_node(self.node_name)
            await self.send_msg_queue.put((node_name, pong_msg))
        return

    async def check_state(self):
        while not self._stop:
            await curio.sleep(NODE_TIMEOUT)
            online_nodes = self.gossip_msg.update_nodes_status()
            anyone_see_leader = [i for i in online_nodes if i[1]["leader_online"]]
            # if we cant see the leader, do we need a election?
            if not self.gossip_msg.am_i_leader(self.node_name) and self.gossip_msg.is_leader_offline():
                # there are more then half nodes that cant see the leader!
                if len(online_nodes) >= self.half and not anyone_see_leader:
                    if self.election_delay_ms == -1 and time.time() - self.last_prepare_time > NODE_TIMEOUT:
                        # and we did not start a election!
                        self.election_delay_ms = random.randint(1000, 3000)  # 1s - 3s
                        logger.info("%s need to start a election, delay %s(ms)", self.verbose_name, self.election_delay_ms)
                        await spawn(self.prepare, daemon=True)
            # wait NODE_TIMEOUT to tell cluster state is healthy
            # what if a node switch to offline and online frequently
            if len(online_nodes) < self.half:
                self.cluster_state = ClusterState.unhealthy
                msg = "im(%s) in a minority set(size=%s)" % (self.verbose_name, len(online_nodes) + 1)
                if self.gossip_msg.am_i_leader(self.node_name):
                    msg += " and im the leader"
                if not self.gossip_msg.get_leader():
                    msg += " and no leader elected!"
                elif not anyone_see_leader:
                    msg += " and no one see the leader %s!" % self.gossip_msg.get_leader()
                logger.info(msg)
        return

    async def handle_ping(self, msg_obj):
        """
        response pong
        """
        from_node = msg_obj.from_node
        pong_msg = PongMsg.from_gossip_msg(self.gossip_msg, self)
        pong_msg.set_from_node(self.node_name)
        await self.send_msg_queue.put((from_node, pong_msg))
        return

    async def handle_pong(self, msg_obj: PongMsg):
        """
        update gossip
        """
        # TODO: save prepare proposal number into file
        from_node = msg_obj.from_node
        self.gossip_msg.update_node_last_pong_time(from_node)
        self.gossip_msg.set_node_online(from_node, msg_obj.get_data())
        if msg_obj.prepare_pn < self.prepare_pn or msg_obj.leader_prepare_pn < self.gossip_msg.leader_prepare_pn:
            return
        if msg_obj.leader_prepare_pn > self.gossip_msg.leader_prepare_pn:
            logger.info("%s(pn=%s, leader=%s, leader_prepare_pn=%s) upgrade new leader(%s, pn=%s) base on pong from node %s(pn=%s)",
                        self.verbose_name, self.prepare_pn, self.gossip_msg.leader, self.gossip_msg.leader_prepare_pn,
                        msg_obj.leader, msg_obj.leader_prepare_pn,
                        msg_obj.from_node, msg_obj.prepare_pn,
                        )
            self.gossip_msg.leader_prepare_pn = msg_obj.leader_prepare_pn
            self.gossip_msg.set_leader(msg_obj.leader)
            if msg_obj.prepare_pn > self.prepare_pn:
                self.prepare_pn = msg_obj.prepare_pn
            return
        if msg_obj.prepare_pn == self.prepare_pn:
            if self.gossip_msg.am_i_leader(self.node_name):
                # sync log data
                self.log_data_manager.may_need_to_sync_chosen(msg_obj.from_node, msg_obj.all_chosen_index)
            elif msg_obj.leader and msg_obj.leader_online and self.gossip_msg.is_leader_offline():
                if self.gossip_msg.am_i_leader(msg_obj.leader) and msg_obj.timestamp - time.time() >= NODE_TIMEOUT:
                    logger.info("%s found out leader is still alive from node %s, but we dont do anything for now",
                                self.verbose_name, msg_obj.from_node,
                                )
                    # TODO: issue a transmission
        return

    async def handle_prepare(self, msg_obj: PrepareMsg):
        """
        we only accept prepare when no one can see a leader!
        """
        if self.gossip_msg.is_leader_online():
            # someone can ask for transmission, rather then sending a prepare
            logger.debug("%s found leader is online, we do not response a prepare from node %s!",
                         self.verbose_name, msg_obj.from_node)
            return
        if time.time() - self.last_prepare_time < NODE_TIMEOUT:
            # prevent too many preparation request coming
            logger.debug("%s got too many prepare msg, ignore prepare msg from node %s",
                         self.verbose_name,
                         msg_obj.from_node)
            return
        prepare_ack_msg = PrepareACKMsg()
        prepare_ack_msg.set_from_node(self.node_name)
        logger.info("%s handle prepare from node %s, my prepare_pn %s, prepare msg pn %s",
                    self.verbose_name, msg_obj.from_node,
                    self.prepare_pn, msg_obj.prepare_pn,
                    )
        if msg_obj.prepare_pn <= self.prepare_pn:
            prepare_ack_msg.set_status_fail()
            logger.info("%s(pn=%s) send prepare ack fail to node %s(pn=%s)", self.verbose_name, self.prepare_pn,
                        msg_obj.prepare_pn, msg_obj.from_node)
        else:
            self.last_prepare_time = time.time()
            self.prepare_pn = msg_obj.prepare_pn
            prepare_ack_msg.set_status_success()
            prepare_ack_msg.set_all_chosen_index(self.log_data_manager.all_chosen_index)
            prepare_ack_msg.set_log_index(self.log_data_manager.log_index)
            logger.info("%s send prepare ack suc to node %s", self.verbose_name, msg_obj.from_node)
        prepare_ack_msg.set_prepare_pn(self.prepare_pn)
        await self.send_msg_queue.put((msg_obj.from_node, prepare_ack_msg))
        return

    async def handle_prepare_ack(self, msg_obj: PrepareACKMsg):
        if msg_obj.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare ack from node %s with pn %s", self.verbose_name, msg_obj.from_node, msg_obj.prepare_pn)
            return
        if msg_obj.prepare_pn > self.prepare_pn:
            logger.warning("%s get a larger pn %s prepare ack from node %s, thats weird")
            return
        if not self.prepare_ack_evt:
            logger.error("self.prepare_ack_evt is None, why?")
            return
        await self.prepare_ack_evt.get_ack(msg_obj)
        return

    async def handle_prepare_sync(self, msg: PrepareSyncMsg):
        if msg.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare sync from node %s with pn %s", self.verbose_name, msg.from_node, msg.prepare_pn)
            return
        if msg.prepare_pn > self.prepare_pn:
            logger.warning("%s(pn=%s) get a larger pn %s prepare sync from node %s, thats weird",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn,
                           msg.from_node)
            return
        data = self.log_data_manager.log_data[msg.min_index: msg.max_index+1]
        resp = PrepareSyncACKMsg()
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_from_node(self.node_name)
        resp.set_sync_data(data)
        resp.set_status_success()
        resp.set_min_max_index(msg.min_index, msg.max_index)
        await self.send_msg_queue.put((msg.from_node, resp))
        return

    async def handle_prepare_sync_ack(self, msg: PrepareSyncACKMsg):
        if msg.prepare_pn < self.prepare_pn:
            logger.debug("%s get a outdated prepare sync ack from node %s with pn %s", self.verbose_name, msg_obj.from_node, msg_obj.prepare_pn)
            return
        if msg.prepare_pn > self.prepare_pn:
            logger.warning("%s get a larger pn %s prepare sync ack from node %s, thats weird")
            return
        if not self.prepare_sync_ack_evt:
            logger.error("self.prepare_sync_ack_evt is None, why?")
            return
        await self.prepare_sync_ack_evt.get_ack(msg)
        return

    async def prepare(self):
        if self.election_delay_ms == -1:
            logger.info("%s preare before sleep, election was canceled at somewhere, return", self.verbose_name)
            return
        await curio.sleep(self.election_delay_ms / 1000)
        if self.election_delay_ms == -1:
            logger.info("%s prepare wake up, but election was canceled at somewhere, return", self.verbose_name)
            return
        if self.gossip_msg.is_leader_online():
            logger.info("%s have leader online, no need to start a election!", self.verbose_name)
            self.election_delay_ms = -1
            return
        if time.time() - self.last_prepare_time < NODE_TIMEOUT:
            logger.info("%s got prepare request at %s, we give up this preparation", self.verbose_name, self.last_prepare_time)
            self.election_delay_ms = -1
            return
        if self.never_attempt_to_acquire_leadership:
            logger.info("%s never attempt to acquire leadership", self.verbose_name)
            self.election_delay_ms = -1
            return
        self.prepare_pn = self.get_next_pn()
        logger.info("@@@@@@@@@@@@%s is going to prepare, prepare_pn=%s !!!!!", self.verbose_name, self.prepare_pn)
        prepare_msg = PrepareMsg(self.prepare_pn)
        prepare_msg.set_from_node(self.node_name)
        self.prepare_ack_evt = MajorityAckEvt(self.prepare_pn, self.half)
        for node_name in self.nodes_map:
            await self.send_msg_queue.put((node_name, prepare_msg))
        # wait for majority
        await self.prepare_ack_evt.wait()
        logger.info("%s wait prepare status %s", self.verbose_name, self.prepare_ack_evt.status)
        # we may got someone response us with prepare proposal number, so go to check them
        self.prepare_pn = max(self.prepare_pn, self.prepare_ack_evt.get_max_prepare_ack_pn())
        if not self.prepare_ack_evt.is_suc():
            # fail, maybe we need to start another election
            logger.warning("%s does not get more than half prepare ack, return", self.verbose_name)
        else:
            # sync log data and broadcast chosen
            msgs = self.prepare_ack_evt.get_all_success_msgs()
            # [min_index, max_index], close bracket
            min_index = min([i.all_chosen_index for i in msgs if i.all_chosen_index] + [self.log_data_manager.all_chosen_index or 0], default=0)
            max_index = max([i.log_index for i in msgs] + [self.log_data_manager.log_index])
            prepare_sync_msg = PrepareSyncMsg()
            prepare_sync_msg.set_prepare_pn(self.prepare_pn)
            prepare_sync_msg.set_from_node(self.node_name)
            prepare_sync_msg.set_min_index(min_index)
            prepare_sync_msg.set_max_index(max_index)
            self.prepare_sync_ack_evt = MajorityAckEvt(self.prepare_pn, self.half, MsgType.PREPARE_SYNC_ACK)
            for node_name in self.nodes_map:
                await self.send_msg_queue.put((node_name, prepare_sync_msg))
            await self.prepare_sync_ack_evt.wait()
            if not self.prepare_sync_ack_evt.is_suc():
                logger.warning("%s does not get more than half prepare sync ack, return", self.verbose_name)
            else:
                # SYNC DATA!!!!
                msgs = self.prepare_sync_ack_evt.get_all_success_msgs()
                self.log_data_manager.sync_prepare_data(self.prepare_pn, msgs)
                # we are the leader!
                # in sometime, we will send the leadership to all of nodes
                logger.info("############## I(%s, pn=%s) am the leader!!!!!!!!", self.verbose_name, self.prepare_pn)
                self.gossip_msg.leader_prepare_pn = self.prepare_pn
                self.gossip_msg.set_leader(self.node_name)
        self.election_delay_ms = -1
        return

    async def handle_info(self, msg: ClientNodeInfoCmd):
        info_key = msg.info_key  # info_key is all for now
        resp = ClientNodeInfoResult()
        resp.set_from_node(self.node_name)
        info = {"leader": self.gossip_msg.get_leader(),
                "leader_online": self.gossip_msg.is_leader_online(),
                "cluster_state": self.cluster_state.value,
                "prepare_pn": self.prepare_pn,
                "nodes": {},
                "all_chosen_index": self.log_data_manager.all_chosen_index,
                "log_index": self.log_data_manager.log_index,
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

    async def handle_choose(self, choose_cmd: ClientChooseCmd):
        resp = ClientChooseResult()
        resp.set_from_node(self.node_name)
        if not self.gossip_msg.am_i_leader(self.node_name):
            logger.warning("I(%s) am not the leader, stop asking me to choose a value", self.verbose_name)
            resp.set_status_fail()
            if self.gossip_msg.get_leader():
                resp.set_reason("i am not leader, leader is %s" % self.gossip_msg.get_leader())
            else:
                resp.set_reason("leader is unknown")
            return resp.get_bytes()
        elif self.cluster_state == ClusterState.unhealthy:
            resp.set_status_fail()
            resp.set_reason("cluster is unhealthy state!")
            return resp.get_bytes()
        value = choose_cmd.value
        req_id = choose_cmd.req_id
        req_id_state = self.log_data_manager.get_req_id_state(req_id)
        if req_id_state == LearnState.suc:
            resp.set_status_fail()
            resp.set_reason("request was success, do not issue again!")
            return resp.get_bytes()
        elif req_id_state == LearnState.timeout:
            resp.set_status_fail()
            resp.set_reason("request is waiting for chosen, do not issue again!")
            return resp.get_bytes()
        log_index = self.log_data_manager.get_next_log_index()
        accept_msg = AcceptMsg()
        accept_msg.set_from_node(self.node_name)
        accept_msg.set_prepare_pn(self.prepare_pn)
        accept_msg.set_pos_and_value(log_index, value)
        accept_msg.set_req_id(req_id)
        accept_ack_evt = MajorityAckEvt(self.prepare_pn, self.half, resp_type=MsgType.ACCEPT_ACK)
        self.accept_ack_evts[log_index] = accept_ack_evt
        for node_name in self.nodes_map:
            await self.send_msg_queue.put((node_name, accept_msg))
        # wait for majority
        await accept_ack_evt.wait()
        logger.debug("%s wait accept for log index %s, value %s return status %s",
                     self.verbose_name, log_index, value, accept_ack_evt.status)
        del self.accept_ack_evts[log_index]
        if not accept_ack_evt.is_suc():
            resp.set_status_timeout()
            resp.set_reason("i lost some nodes")
            max_pn = accept_ack_evt.get_max_prepare_ack_pn()
            if max_pn > self.prepare_pn:
                logger.warning("%s lost our leadership when recv accept ack for pos %s, value %s, max_pn %s, self.prepare_pn %s",
                               self.verbose_name, log_index, value,
                               max_pn, self.prepare_pn)
                resp.set_reason("i lost my leadership!")
            self.log_data_manager.mark_timeout_and_need_retry(log_index, value, req_id, self.prepare_pn)
        else:
            resp.set_status_success()
            self.log_data_manager.add_chosen(self.prepare_pn, log_index, value, req_id)
        return resp.get_bytes()

    async def handle_accept(self, msg_obj: AcceptMsg):
        if self.gossip_msg.am_i_leader(self.node_name):
            logger.warning("%s get accept request from %s, but i am the leader, ignore this accept",
                           self.verbose_name, msg_obj.from_node)
            return
        if not self.gossip_msg.am_i_leader(msg_obj.from_node):
            logger.warning("%s get accept request from %s, but its not my leader(%s), ignore this accept",
                           self.verbose_name, msg_obj.from_node, self.gossip_msg.get_leader())
            return
        log_index, value = msg_obj.pos, msg_obj.value
        req_id = msg_obj.req_id
        resp = AcceptAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos(log_index)
        if msg_obj.prepare_pn < self.prepare_pn:
            logger.error("%s get a accept request with smaller prepare_pn %s from node %s, my pn %s, ignore this accept",
                         self.verbose_name, msg_obj.prepare_pn, msg_obj.from_node,
                         self.prepare_pn)
            return
        else:
            self.log_data_manager.mark_slot_accepted(self.prepare_pn, log_index, value, req_id)
            resp.set_state_success()
        await self.send_msg_queue.put((msg_obj.from_node, resp))
        return

    async def handle_accept_ack(self, msg: AcceptAckMsg):
        accept_ack_evt = self.accept_ack_evts.get(msg.pos, None)
        if not accept_ack_evt:
            return
        await accept_ack_evt.get_ack(msg)
        return

    async def background_batch_accept(self):
        while not self._stop:
            await curio.sleep(NODE_TIMEOUT + random.randint(1000, 2000) / 1000)
            if not self.gossip_msg.am_i_leader(self.node_name):
                continue
            batch_data = self.log_data_manager.get_retry_accept_list()
            logger.debug("background_batch_accept %s", batch_data)
            if not batch_data:
                continue
            msg = BatchAcceptMsg()
            msg.set_data(batch_data)
            msg.set_prepare_pn(self.prepare_pn)
            msg.set_from_node(self.node_name)
            for node_name in self.nodes_map:
                await self.send_msg_queue.put((node_name, msg))
        return

    async def handle_batch_accept(self, msg: BatchAcceptMsg):
        from_who = msg.from_node
        if not self.gossip_msg.am_i_leader(from_who):
            logger.warning("%s got a batch accept from %s, but it is not my leader(%s)",
                           self.log_data_manager, from_who, self.gossip_msg.get_leader())
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s got a batch accept from %s, but its pn (%s)is smaller then ours(%s)",
                           self.log_data_manager, from_who, msg.prepare_pn, self.prepare_pn)
            return
        pos_list = []
        for pos, value, req_id in msg.data:
            self.log_data_manager.mark_slot_accepted(pos, value, req_id)
            pos_list.append(pos)
        resp = BatchAcceptAckMsg()
        resp.from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos_list(pos_list)
        await self.send_msg_queue.put((from_who, resp))
        return

    async def handle_batch_accept_ack(self, msg: BatchAcceptAckMsg):
        if not self.gossip_msg.am_i_leader(self.node_name):
            logger.warning("im(%s) not the leader(%s), but got a batch accept ack from %s",
                           self.verbose_name, self.gossip_msg.get_leader(), msg.from_node)
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s(pn=%s) got a batch chosen ack with smaller pn %s from %s",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn, msg.from_node)
            return
        self.log_data_manager.update_from_batch_accept_ack(self.prepare_pn, msg)
        return

    async def background_batch_chosen(self):
        while not self._stop:
            st = NODE_TIMEOUT + random.randint(1000, 2000) / 1000
            await curio.sleep(st)
            if not self.gossip_msg.am_i_leader(self.node_name):
                continue
            batch_chosen_data = self.log_data_manager.get_chosen_broadcast_list()
            logger.debug("background_batch_chosen %s", batch_chosen_data)
            for node_name in batch_chosen_data:
                if not self.gossip_msg.is_node_online(node_name):
                    continue
                msg = BatchChosenMsg()
                msg.set_from_node(self.node_name)
                msg.set_prepare_pn(self.prepare_pn)
                msg.set_data(batch_chosen_data[node_name])
                await self.send_msg_queue.put((node_name, msg))
        return

    async def handle_batch_chosen(self, msg: BatchChosenMsg):
        from_who = msg.from_node
        if not self.gossip_msg.am_i_leader(from_who):
            logger.warning("%s got a batch chosen from %s, but it is not my leader(%s)",
                           self.log_data_manager, from_who, self.gossip_msg.get_leader())
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s got a batch chosen from %s, but its pn (%s)is smaller then ours(%s)",
                           self.log_data_manager, from_who, msg.prepare_pn, self.prepare_pn)
            return
        pos_list = []
        for pos, value, req_id in msg.data:
            self.log_data_manager.mark_slot_chosen(msg.prepare_pn, pos, value, req_id)
            pos_list.append(pos)
        resp = BatchChosenAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos_list(pos_list)
        await self.send_msg_queue.put((from_who, resp))
        return

    async def handle_batch_chosen_ack(self, msg: BatchChosenAckMsg):
        if not self.gossip_msg.am_i_leader(self.node_name):
            logger.warning("im(%s) not the leader(%s), but got a batch chosen ack from %s",
                           self.verbose_name, self.gossip_msg.get_leader(), msg.from_node)
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s(pn=%s) got a batch chosen ack with smaller pn %s from %s",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn, msg.from_node)
            return
        self.log_data_manager.update_from_batch_chosen_ack(msg)
        return

    async def handle_learn(self, msg_obj: ClientLearnCMD):
        """
        client issue a learn request
        """
        req_id = msg_obj.req_id
        state = self.log_data_manager.get_req_id_state(req_id)
        resp = ClientLearnResult()
        resp.set_state(state)
        return resp.get_bytes()

    async def handle_get_log_data(self, msg: ClientGetLogDataCMD):
        min_index, max_index = msg.min_index, msg.max_index
        data = self.log_data_manager.log_data[min_index: max_index+1]
        resp = ClientGetLogDataResult()
        resp.set_from_node(self.node_name)
        resp.set_log_data(data)
        return resp.get_bytes()

    async def handle_disable_leadership(self, msg: ClientDisableLeadershipCMD):
        if msg.flag == 1:
            self.never_attempt_to_acquire_leadership = True
        else:
            self.never_attempt_to_acquire_leadership = False
        resp = ClientDisableLeadershipResult()
        return resp.get_bytes()

    def run(self):
        logger.info("%s Running" % self.verbose_name)
        self.background_io_th.start()
        try:
            run(self.io_server)
        except KeyboardInterrupt:
            pass
        logger.info("%s return" % self.verbose_name)
        return


def run_machines():
    nodes_map = {1: ("127.0.0.1", 6666),
                 2: ("127.0.0.1", 6667),
                 3: ("127.0.0.1", 6668),
                 }
    node_id = int(sys.argv[1])
    level = logging.INFO
    if len(sys.argv) >= 3:
        level = getattr(logging, sys.argv[2].upper())
    logging.getLogger("multi-paxos").setLevel(level)
    machine = LogStateMatchine(node_id, nodes_map)
    machine.run()
    return


def main():
    run_machines()
    return


if __name__ == "__main__":
    main()


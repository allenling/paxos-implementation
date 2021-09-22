from enum import Enum
import time
import json


NODE_TIMEOUT = 10  # seconds
IOMSG_FIX_LEN = 1500


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
    CANCEL = 3


class ClusterState(Enum):
    healthy = 0
    unhealthy = 1
    idle = 2


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
        self.prepare_pn = -1
        template = {"status": self.OFFLINE,
                    "last_ping_time": -1, "sock": None,
                    "last_pong_time": float("inf"),
                    "gossip": {"leader": None, "leader_online": False, "prepare_pn": -1, "leader_cluster_state": None},
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

    def get_node_leader_cluster_state(self, node_name):
        node_gossip = self.infos.get(node_name, None)
        ret = None if node_gossip is None else node_gossip["gossip"]["leader_cluster_state"]
        return ret

    def is_leader_online(self):
        if self.leader:
            if self.myself == self.leader:
                return True
            return self.infos[self.leader]["sock"] is not None and self.infos[self.leader]["status"] == self.ONLINE
        return False

    def get_leader_cluster_state(self):
        if self.leader:
            return self.get_node_leader_cluster_state(self.leader)
        return

    def is_leader_offline(self):
        return not self.is_leader_online()

    def is_leader(self, node_name):
        return self.leader and self.leader == node_name

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
            if self.is_node_online(node_name):
                # someone is online and can see a leader
                res.append([node_name, node_gossip_info])
        res = sorted(res, key=lambda n: n[1]["prepare_pn"])
        return res

    def update_nodes_status(self):
        now_time = time.time()
        for node_name, info in self.infos.items():
            if info["sock"] and info["last_pong_time"] - now_time < NODE_TIMEOUT:
                info["status"] = self.ONLINE
            else:
                info["status"] = self.OFFLINE
        online_nodes = self.get_online_nodes()
        return online_nodes

class PingPongMsg:

    def __init__(self):
        self.leader = None
        self.leader_online = None
        self.prepare_pn = None
        self.all_chosen_index = None
        self.leader_cluster_state = None
        return

    def get_data(self):
        return {"leader": self.leader, "leader_online": self.leader_online, "prepare_pn": self.prepare_pn,
                "all_chosen_index": self.all_chosen_index,
                "leader_cluster_state": self.leader_cluster_state}

    @classmethod
    def from_gossip_msg(cls, gossip_msg_obj: GossipMsg, machine):
        msg = cls()
        msg.leader = gossip_msg_obj.leader
        msg.leader_online = gossip_msg_obj.is_leader_online()
        msg.prepare_pn = machine.prepare_pn
        msg.all_chosen_index = machine.log_data_manager.all_chosen_index
        if gossip_msg_obj.is_leader(machine.node_name):
            msg.leader_cluster_state = machine.cluster_state.name
        else:
            msg.leader_cluster_state = gossip_msg_obj.get_leader_cluster_state()
        return msg

    @classmethod
    def _from_json(cls, jdata):
        msg = cls()
        msg.leader = jdata["leader"]
        msg.leader_online = jdata["leader_online"]
        msg.prepare_pn = jdata["prepare_pn"]
        msg.all_chosen_index = jdata["all_chosen_index"]
        msg.leader_cluster_state = jdata["leader_cluster_state"]
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
        return {"state": self.state.name, "prepare_pn": self.prepare_pn,
                "all_chosen_index": self.all_chosen_index, "log_index": self.log_index,
                }

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareACKMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.state = MsgStatus[jdata["state"]]
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
        # sync_data=[(pos, value, req_id, state, prepare_pn), ], sync_data contains all values from all_chosen_index to log_index
        self.sync_data = []
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
        self.sync_data = [(i.pos, i.value, i.req_id, i.state.value, i.prepare_pn) for i in self.sync_data]
        return

    def set_min_max_index(self, min_index, max_index):
        self.min_index = min_index
        self.max_index = max_index
        return

    def get_data(self):
        return {"state": self.state.value, "prepare_pn": self.prepare_pn,
                "sync_data": self.sync_data,
                "min_index": self.min_index, "max_index": self.max_index,
                }

    @classmethod
    def _from_json(cls, jdata):
        msg = PrepareSyncACKMsg()
        msg.prepare_pn = jdata["prepare_pn"]
        msg.state = MsgStatus(jdata["state"])
        msg.sync_data = [(i[0], i[1], i[2], i[3], i[4]) for i in jdata["sync_data"]]
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
        self.data = data
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
        return {"pos_list": self.pos_list, "prepare_pn": self.prepare_pn}

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
        self.data = data
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


class ClientCMDType(Enum):
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
    IGNORE_ACCEPT = 10
    IGNORE_ACCEPT_ACK = 11
    DISABLE_PONG = 12
    DISABLE_PONG_ACK = 13
    GET_RETRY_ACCEPT_LIST = 14
    GET_RETRY_ACCEPT_LIST_ACK = 15


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
        data["cmd_type"] = self.cmd_type.name
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

class ChooseState(Enum):
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
        return {"state": self.state.name, "reason": self.reason}

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


class LearnState(Enum):
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
        return {"state": self.state.name, "pos": self.pos,
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


class ClientIgnoreAcceptCMD(ClientMsg):
    cmd_type = ClientCMDType.IGNORE_ACCEPT
    flag = None

    def get_cmd_data(self):
        return {"flag": self.flag}

    def set_flag(self, f):
        self.flag = f
        return

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientIgnoreAcceptCMD()
        obj.flag = jdata["flag"]
        return obj


class ClientIgnoreAcceptAck(ClientMsg):
    cmd_type = ClientCMDType.IGNORE_ACCEPT_ACK

    def get_cmd_data(self):
        return {}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientIgnoreAcceptAck()
        return obj


class ClientDisablePongCMD(ClientMsg):
    cmd_type = ClientCMDType.DISABLE_PONG
    flag = None

    def get_cmd_data(self):
        return {"flag": self.flag}

    def set_flag(self, f):
        self.flag = f
        return

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientDisablePongCMD()
        obj.flag = jdata["flag"]
        return obj


class ClientDisablePongAck(ClientMsg):
    cmd_type = ClientCMDType.DISABLE_PONG_ACK

    def get_cmd_data(self):
        return {}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientDisablePongAck()
        return obj


class ClientGetRetryAcceptListCMD(ClientMsg):
    cmd_type = ClientCMDType.GET_RETRY_ACCEPT_LIST

    def get_cmd_data(self):
        return {}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientGetRetryAcceptListCMD()
        return obj


class ClientGetRetryAcceptListAck(ClientMsg):
    cmd_type = ClientCMDType.GET_RETRY_ACCEPT_LIST_ACK
    data = {}

    def set_data(self, data):
        self.data = data
        return

    def get_cmd_data(self):
        return {"data": self.data}

    @classmethod
    def _cmd_from_json(cls, jdata):
        obj = ClientGetRetryAcceptListAck()
        obj.data = jdata["data"]
        return obj


def main():
    return

if __name__ == "__main__":
    main()

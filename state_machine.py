

import dataclasses
import random
import json
import time

import curio
from curio.socket import *


import messages


NO_OP = "no_op"


@dataclasses.dataclass
class LogEntry:
    term: int = -100
    value: str = NO_OP
    idx: int = -1
    chosen: bool = False


@dataclasses.dataclass
class LeaderInfo(messages.Msg):
    term: int = -1
    online: bool = False
    address: tuple | None = None
    last_ts: float | None = 0
    working: bool = False


@dataclasses.dataclass
class Heartbeat(messages.Msg):
    leader_info: LeaderInfo


@dataclasses.dataclass
class Inquery(messages.Msg):
    pass


@dataclasses.dataclass
class InqueryResp(messages.Msg):
    max_term: int
    from_addr: tuple
    leader_info: LeaderInfo

    @classmethod
    def from_dict(cls, jdata):
        data = jdata["data"]
        max_term = data["max_term"]
        leader_info = LeaderInfo(**data["leader_info"])
        return InqueryResp(max_term=max_term, from_addr=tuple(data["from_addr"]), leader_info=leader_info)


@dataclasses.dataclass
class ElectionProposal(messages.Msg):
    term: int
    candidate: tuple


@dataclasses.dataclass
class ElectionPromise(messages.Msg):
    term: int
    candidate: tuple
    left_idx: int
    right_idx: int


@dataclasses.dataclass
class ElectionReject(messages.Msg):
    max_term: int


@dataclasses.dataclass
class CloseConnection(messages.Msg):
    address: tuple


@dataclasses.dataclass
class Empty(messages.Msg):
    pass


@dataclasses.dataclass
class LogGapReq(messages.Msg):
    pass


@dataclasses.dataclass
class LogGapResp(messages.Msg):
    log_entries: list[LogEntry] | None = None

    @classmethod
    def from_dict(cls, jdata):
        data = jdata["data"]
        log_entries = []
        for log_entry in data:
            log_entries.append(LogEntry(**log_entry))
        return LogGapResp(log_entries=log_entries)


@dataclasses.dataclass
class WriteReq(messages.Msg):
    value: str


@dataclasses.dataclass
class WriteResp(messages.Msg):
    succ: bool
    reason: str
    value: str


@dataclasses.dataclass
class ReplicateReq(messages.Msg):
    log_entry: LogEntry


@dataclasses.dataclass
class ReplicateResp(messages.Msg):
    succ: bool = True


@dataclasses.dataclass
class BatchReplicateReq(messages.Msg):
    term: int
    log_entries: list[LogEntry]


@dataclasses.dataclass
class BatchReplicateResp(messages.Msg):
    succ: bool


@dataclasses.dataclass
class ChosenReq(messages.Msg):
    log_entry: LogEntry


@dataclasses.dataclass
class BatchChosenReq(messages.Msg):
    term: int
    log_entries: list[LogEntry]


@dataclasses.dataclass
class GetEntryReq(messages.Msg):
    left: int = 0
    right: int = 0


@dataclasses.dataclass
class GetEntryResp(messages.Msg):
    log_entries: list[LogEntry] | None


@dataclasses.dataclass
class SyncLogReq(messages.Msg):
    leftmost: int
    rightmost: int


@dataclasses.dataclass
class SyncLogResp(messages.Msg):
    log_entries: list[LogEntry]
    
    @classmethod
    def from_str(cls, data):
        obj = super(SyncLogResp, cls).from_str(data)
        obj.log_entries = [LogEntry(**sub_data) for sub_data in obj.log_entries]
        return obj


@dataclasses.dataclass
class WaitForLeaderReq(messages.Msg):
    old_leader: tuple | None


@dataclasses.dataclass
class LeaderHBAction(messages.Msg):
    ignore: bool


@dataclasses.dataclass
class Config(messages.Msg):
    bg_invt: float | None = None
    dead_nodes: list[tuple] | None = None
    clear_dead_nodes: bool = False


class StateMachine:
    INVT = 0.5
    LEADER_HB = 1.5

    def __init__(self, addr="127.0.0.1", port=10010, servers_list=None, config: Config | None = None):
        self._log = [LogEntry(idx=i) for i in range(10)]
        self.left_idx = -1
        self.right_idx = -1
        self.gap = 10
        self.batch_replicate_list = []
        self.batch_chosen_list = []
        self.addr = addr
        self.port = port
        self.kernel = None
        self.sock = None
        self.leader_info = LeaderInfo()
        self.lock = curio.Lock()
        self.election_proposal: ElectionProposal | None = None
        self.max_term = -1
        self._stopped = curio.Event()
        self.servers_list = [i for i in servers_list if i != self.address]
        self.half_len = len(servers_list) // 2
        self._leader_evt = curio.Event()
        self.ignore_leader_hb = False
        self.bg_invt = None
        if config and config.bg_invt:
            self.bg_invt = config.bg_invt
        self.dead_nodes = set()
        return

    @property
    def info(self):
        leader = None
        if self.self_leader:
            leader = f"Self,True,{self.leader_info.working}"
        elif self.is_leader_online():
            leader = f"{self.leader_info.address},{self.leader_info.online},{self.leader_info.working}"
        return f"Server<{self.address},L={leader}>"

    async def send_timeout(self, address, msg: messages.Msg):
        async with socket(AF_INET, SOCK_STREAM) as sock:
            try:
                if address in self.dead_nodes:
                    raise OSError
                await curio.timeout_after(0.1, sock.connect, address)
            except (OSError, curio.TaskTimeout):
                return
            await sock.sendall(msg.to_bytes())
            try:
                ret = await curio.timeout_after(0.1, sock.recv, 40960)
            except curio.TaskTimeout:
                ret = None
        return ret

    async def send_to_all(self, msg: messages.Msg, expected_msg=None):
        async with curio.TaskGroup() as g:
            for address in self.servers_list:
                await g.spawn(self.send_timeout, address, msg)
        resps = [None] * len(self.servers_list)
        for idx, resp in enumerate(g.results):
            if not resp:
                continue
            if not expected_msg:
                resps[idx] = messages.Msg.from_str(resp)
            else:
                resps[idx] = expected_msg.from_str(resp)
        resps = [resp for resp in resps if resp]
        return resps

    @property
    def address(self):
        return self.addr, self.port

    def is_leader_online(self):
        if not self.leader_info or not self.leader_info.online:
            return False
        if self.leader_info.address == self.address:
            return True
        t = time.time()
        d = t - self.leader_info.last_ts
        if d > self.LEADER_HB:
            self.leader_info.online = False
            self.leader_info.working = False
            return False
        return True

    def is_leader(self, address: list | tuple):
        return self.leader_info.address == tuple(address)

    @property
    def self_leader(self) -> bool:
        return self.leader_info.address == self.address

    def update_leader_info(self, leader_info: LeaderInfo):
        self.leader_info = dataclasses.replace(leader_info, online=True, last_ts=time.time())
        return

    def get_heartbeat_msg(self):
        return Heartbeat(leader_info=self.leader_info)

    async def background_task(self):
        if self.bg_invt is None:
            self.bg_invt = self.INVT + random.randint(0, 100)/1000
        print(f"{self.info} bg invt {self.bg_invt}")
        while not self._stopped.is_set():
            await curio.sleep(self.bg_invt)
            if not self.is_leader_online():
                await self.start_election()
            if self.self_leader:
                heartbeat = self.get_heartbeat_msg()
                resps = await self.send_to_all(heartbeat)
                self.leader_info.working = len(resps) >= self.half_len
                # print(f"{self.info} done sending hb {time.time()}")
        return

    async def start_election(self):
        st = random.randint(1, 10)/10
        print(f"{self.info} is going to sleep for {st} seconds before election")
        await curio.sleep(st)
        print(f"{self.info} start_election")
        if self.is_leader_online():
            print(f"{self.info} start_election return 1")
            return
        # ask the others for leader info
        inquery = Inquery()
        resps = await self.send_to_all(inquery, expected_msg=InqueryResp)
        if self.is_leader_online():
            print(f"{self.info} start_election return 2")
            return
        print(f"{self.info} got responses for inquery {resps}")
        term_leaders = {}
        max_term = float("-inf")
        for resp in resps:
            max_term = max(max_term, resp.max_term)
            tmp = resp.leader_info
            if tmp.term not in term_leaders:
                term_leaders[tmp.term] = []
            term_leaders[tmp.term].append(tmp)
        max_leader_infos = term_leaders[max(term_leaders.keys())]
        for leader_info in max_leader_infos:
            if leader_info.online and leader_info.working:
                print(f"{self.info} start_election return 3 {leader_info}")
                return
        self.max_term = max(self.max_term, max_term, self.leader_info.term) + 1
        print(f"{self.info} max_term {self.max_term}")
        if self.election_proposal and self.election_proposal.term >= self.max_term:
            self.max_term = max(self.election_proposal.term, self.max_term)
            print(f"{self.info}'s got an election proposal {self.election_proposal}")
            return
        election_proposal = ElectionProposal(term=self.max_term, candidate=self.address)
        resps = await self.send_to_all(election_proposal)
        promised = []
        rejected = []
        for i in resps:
            if type(i) == ElectionReject:
                rejected.append(i)
            else:
                promised.append(i)
        print(f"{self.info} election_proposal responses:")
        print(f"promised {promised}")
        print(f"rejected {rejected}")
        if any([i.max_term > self.max_term for i in rejected]):
            return
        if len(promised) < self.half_len:
            self.max_term += 1
            return
        # no reconfiguration, gap is trivial
        # we can write all the entries whose index greater than the max right idx
        rightmost = self.right_idx = max([i.right_idx for i in promised] + [self.right_idx])
        leftmost = min([i.left_idx + 1 for i in promised] + [self.left_idx + 1])
        lnfo = LeaderInfo(address=self.address, term=self.max_term, working=True, online=True, last_ts=time.time())
        self.update_leader_info(lnfo)
        await self._leader_evt.set()
        print(f"{self.info} is the leader in the term of {self.max_term}")
        await curio.spawn(self.sync_log_entries, leftmost, rightmost, daemon=True)
        return

    async def sync_log_entries(self, leftmost, rightmost):
        if leftmost == 0 and rightmost == -1:
            return
        while True:
            req = SyncLogReq(leftmost=leftmost, rightmost=rightmost)
            resps = await self.send_to_all(req, expected_msg=SyncLogResp)
            resps = [resp for resp in resps if resp]
            if len(resps) < self.half_len:
                await curio.sleep(0.1)
                continue
            if leftmost > rightmost:
                return
            print(f"sync_log_entries {leftmost}, {rightmost}, {resps}")
            entries_map = {i: [] for i in range(leftmost, rightmost+1)}
            for resp in resps:
                for entry in resp.log_entries:
                    entries_map[entry.idx].append(entry)
            for entry in self._log[leftmost: rightmost + 1]:
                entries_map[entry.idx].append(entry)
            print(f"entries_map {entries_map}")
            sync_entries = []
            for idx in range(leftmost, rightmost + 1):
                entry = LogEntry(term=self.max_term, idx=idx, chosen=True)
                candidate_entries = [entry for entry in entries_map[idx] if entry.value != NO_OP]
                if candidate_entries:
                    tmp = sorted(candidate_entries, key=lambda n: n.term)
                    entry.value = tmp[0].value
                sync_entries.append(entry)
                self._log[idx] = entry
            req = BatchChosenReq(term=self.max_term, log_entries=sync_entries)
            await self.send_to_all(req)
            break
        return

    async def handle_synclogreq(self, client, address, msg: SyncLogReq):
        entries = self._log[msg.leftmost:msg.rightmost+1]
        resp = SyncLogResp(log_entries=entries)
        await client.sendall(resp.to_bytes())
        return

    async def handle_writereq(self, client, address, msg: WriteReq):
        # write request from the client
        if not self.self_leader:
            await self.send_to_all(WriteResp(succ=False,
                                             reason=f"the leader is {self.leader_info.address}",
                                             value=msg.value),
                                   )
            return
        val = str(msg.value)
        self.right_idx += 1
        idx = self.right_idx
        log_entry = LogEntry(term=self.max_term, value=val, idx=idx, chosen=False)
        self._log[idx] = log_entry
        resps = await self.send_to_all(ReplicateReq(log_entry=log_entry))
        if len(resps) < self.half_len:
            await client.sendall(WriteResp(succ=False,
                                           reason="less than a majority of nodes alive!",
                                           value=msg.value,
                                           ).to_bytes())
            self.leader_info.working = False
            print(f"{self.info} less than a majority of nodes alive now!")
            return
        succ = [resp for resp in resps if resp.succ]
        if len(succ) < self.half_len:
            await client.sendall(WriteResp(succ=False,
                                           reason="waiting",
                                           value=msg.value,
                                           ).to_bytes())
            self.batch_replicate_list.append(log_entry)
            return
        log_entry.chosen = True
        self.update_left_idx()
        await client.sendall(WriteResp(succ=True, reason="", value=msg.value).to_bytes())
        chosen_req = ChosenReq(log_entry=log_entry)
        await self.send_to_all(chosen_req)
        return

    async def handle_replicatereq(self, client, address, msg: ReplicateReq):
        if msg.log_entry.term != self.leader_info.term:
            await client.sendall(ReplicateResp(succ=False).to_bytes())
            return
        if self.right_idx < msg.log_entry.idx:
            self.right_idx = msg.log_entry.idx
        self._log[msg.log_entry.idx] = msg.log_entry
        await client.sendall(ReplicateResp(succ=True).to_bytes())
        return

    def update_left_idx(self):
        while True:
            idx = self.left_idx + 1
            if not self._log[idx].chosen:
                break
            self.left_idx = idx
        return

    async def handle_waitforleaderreq(self, client, address, msg: WaitForLeaderReq):
        if not self.is_leader_online() or msg.old_leader == self.leader_info.address:
            self._leader_evt.clear()
            await self._leader_evt.wait()
        await client.sendall(Empty().to_bytes())
        return

    async def handle_chosenreq(self, client, address, msg: ChosenReq):
        if msg.log_entry.term == self.leader_info.term:
            self._log[msg.log_entry.idx] = msg.log_entry
            self.update_left_idx()
        await client.sendall(Empty().to_bytes())
        return

    async def handle_getentryreq(self, client, address, msg: GetEntryReq):
        await client.sendall(GetEntryResp(log_entries=self._log[msg.left:msg.right+1]).to_bytes())
        return

    async def batch_replicate_bg(self):
        while not self._stopped.is_set():
            await curio.sleep(1)
            if not self.batch_replicate_list:
                continue
            print(f"batch_replicate_list {self.batch_replicate_list}")
            entries = [entry for entry in self.batch_replicate_list]
            self.batch_replicate_list = []
            for entry in entries:
                entry.chosen = False
            req = BatchReplicateReq(term=self.max_term, log_entries=entries)
            resps = await self.send_to_all(req)
            succ = [resp for resp in resps if resp.succ]
            if len(succ) < self.half_len:
                self.batch_replicate_list = entries + self.batch_replicate_list
                continue
            for entry in entries:
                entry.chosen = True
            req = BatchChosenReq(term=self.max_term, log_entries=entries)
            await self.send_to_all(req)
        return

    async def handle_batchreplicatereq(self, client, address, msg: BatchReplicateReq):
        resp = BatchReplicateResp(succ=True)
        if msg.term == self.leader_info.term:
            for entry in msg.log_entries:
                self._log[entry.idx] = entry
        else:
            resp.succ = False
        await client.sendall(resp.to_bytes())
        return

    async def handle_config(self, client, address, msg: Config):
        if msg.bg_invt:
            self.bg_invt = msg.bg_invt
        if msg.dead_nodes:
            for node_address in msg.dead_nodes:
                self.dead_nodes.add(tuple(node_address))
        elif msg.clear_dead_nodes:
            self.dead_nodes = set()
        await client.sendall(Empty().to_bytes())
        return

    async def handle_batchchosenreq(self, client, address, msg: BatchChosenReq):
        if msg.term == self.leader_info.term:
            for entry_dict in msg.log_entries:
                entry = LogEntry(**entry_dict)
                self._log[entry.idx] = entry
        await client.sendall(Empty().to_bytes())
        return

    async def handle_electionproposal(self, client, address, msg: ElectionProposal):
        if self.max_term < msg.term:
            self.election_proposal = dataclasses.replace(msg)
            await client.sendall(ElectionPromise(term=msg.term, candidate=msg.candidate,
                                                 left_idx=self.left_idx,
                                                 right_idx=self.right_idx).to_bytes())
            return
        await client.sendall(ElectionReject(max_term=self.max_term).to_bytes())
        return

    async def handle_heartbeat(self, client, address, msg: Heartbeat):
        if self.leader_info.term > msg.leader_info.term:
            print(f"{self.info} handle_heartbeat return @, {self.leader_info.term}, {msg}")
            return
        if self.max_term > msg.leader_info.term:
            print(f"{self.info} handle_heartbeat return !, {self.max_term}, {msg}")
            return
        if msg.leader_info.term == self.leader_info.term and not self.is_leader_online():
            print(f"{self.info} leader {msg} online again")
        if msg.leader_info.term > self.leader_info.term:
            print(f"{self.info} update a new leader {msg}")
        self.update_leader_info(msg.leader_info)
        if not self._leader_evt.is_set():
            await self._leader_evt.set()
        await client.sendall(Empty().to_bytes())
        return

    async def handle_inquery(self, client, address, msg: Inquery):
        self.is_leader_online()
        resp = InqueryResp(leader_info=self.leader_info,
                           from_addr=self.address,
                           max_term=self.max_term)
        await client.sendall(resp.to_bytes())
        return

    async def listen(self):
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.sock.bind((self.addr, self.port))
        self.sock.listen(10)
        async with self.sock:
            while not self._stopped.is_set():
                try:
                    client, address = await curio.timeout_after(1, self.sock.accept)
                except curio.TaskTimeout:
                    continue
                await curio.spawn(self.client_task, client, address, daemon=True)
        return

    async def client_task(self, client, address):
        async with client:
            while not self._stopped.is_set():
                try:
                    data = await curio.timeout_after(1, client.recv, 4096)
                except curio.TaskTimeout:
                    continue
                if not data:
                    break
                jdata = json.loads(data.decode())
                msg = messages.Msg.from_dict(jdata)
                handler = getattr(self, f"handle_{msg.__class__.__name__.lower()}")
                await handler(client, address, msg)
                if self._stopped.is_set():
                    break
        return

    async def handle_close(self, client, address, msg):
        await self._stopped.set()
        return

    async def handle_showinfo(self, client, address, msg: messages.ShowInfo):
        data = {"address": self.address,
                "leader_info": dataclasses.asdict(self.leader_info),
                "logs": [dataclasses.asdict(log) for log in self._log],
                "left_idx": self.left_idx,
                "right_idx": self.right_idx,
                }
        await client.sendall(json.dumps(data, indent=4).encode())
        return

    async def spawn_and_wait(self):
        await curio.spawn(self.listen, daemon=True)
        await curio.spawn(self.background_task, daemon=True)
        await curio.spawn(self.batch_replicate_bg, daemon=True)
        await self._stopped.wait()
        return

    def run(self):
        self.kernel = curio.Kernel()
        self.kernel.run(self.spawn_and_wait, shutdown=True)
        return



def main():
    return


if __name__ == "__main__":
    main()

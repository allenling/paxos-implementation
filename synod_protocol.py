


import curio
from curio.socket import *

from messages import *


class Synod:

    def __init__(self, addr, port):
        self.addr = addr
        self.port = port
        self.sock = None
        self.kernel = None
        self._stopped = curio.Event()
        return

    @property
    def address(self):
        return self.addr, self.port

    async def _on_close(self):
        return

    async def spawn_and_wait(self):
        await curio.spawn(self.listen, daemon=True)
        await self._stopped.wait()
        await self._on_close()
        return

    async def listen(self):
        # print(f"process {os.getpid()} listening on {self.address}")
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.sock.bind((self.addr, self.port))
        self.sock.listen(10)
        # print("Server listening at", self.addr, self.port)
        async with self.sock:
            while not self._stopped.is_set():
                try:
                    client, address = await curio.timeout_after(1, self.sock.accept)
                except curio.TaskTimeout:
                    continue
                # print("Connection from", address)
                await curio.spawn(self.client_task, client, address, daemon=True)
        # print("return listen")
        return

    async def client_task(self, client, address):
        async with client:
            while True:
                data = await client.recv(10000)
                if not data:
                    break
                jdata = json.loads(data.decode())
                # print(f"jdata {jdata}")
                msg = Msg.from_dict(jdata)
                handler = getattr(self, f"handle_{msg.__class__.__name__.lower()}")
                await handler(client, msg)
                if self._stopped.is_set():
                    break
                # await client.sendall(data)
        # print(f"Connection from {addr} closed")
        return

    async def handle_close(self, client, msg):
        await self._stopped.set()
        return

    def run(self):
        self.kernel = curio.Kernel()
        self.kernel.run(self.spawn_and_wait, shutdown=True)
        # print("run returned")
        return


class BallotNumberServer(Synod):

    def __init__(self, addr, port):
        super(BallotNumberServer, self).__init__(addr, port)
        self.n = 0
        self.lock = curio.Lock()
        return

    async def handle_getballotnumberreq(self, client, msg: GetBallotNumberReq):
        async with self.lock:
            if msg.least >= self.n:
                self.n = msg.least + 1
            resp = GetBallotNumberResp(ballot_number=self.n)
            await client.sendall(resp.to_bytes())
            self.n += 1
        return


class Proposer(Synod):

    def __init__(self, addr, port, acceptors_list, ballot_address):
        super(Proposer, self).__init__(addr, port)
        self.acceptors_list = acceptors_list
        self.ballot_address = ballot_address
        self.ballot_sock = None
        self.acceptor_socks = []
        self.last_bn = -1
        self._propose_lock = curio.Lock()
        self.debug = False
        self._p1_resume_evt = curio.Event()
        self._p1_paused_evt = curio.Event()
        self._p2_resume_evt = curio.Event()
        self._p2_paused_evt = curio.Event()
        #
        self._p1_accs_idx = None
        self._p2_accs_idx = None
        self._chosen_evt = curio.Event()
        self._chosen_val = None
        return

    @property
    def info(self):
        return f"Proposer<{self.address}, {self.last_bn}>"

    async def spawn_and_wait(self):
        for address in self.acceptors_list:
            sock = socket(AF_INET, SOCK_STREAM)
            await sock.connect(address)
            self.acceptor_socks.append(sock)
        self.ballot_sock = socket(AF_INET, SOCK_STREAM)
        await self.ballot_sock.connect(self.ballot_address)
        await super(Proposer, self).spawn_and_wait()
        return

    async def _on_close(self):
        await super(Proposer, self)._on_close()
        await self._p1_resume_evt.set()
        await self._p2_resume_evt.set()
        return

    async def handle_showinfo(self, client, msg: ShowInfo):
        info = {"info": self.info,
                "debug": self.debug,
                "p1_paused": self._p1_paused_evt._set,
                "p2_paused": self._p2_paused_evt._set,
                }
        await client.sendall(json.dumps(info, indent=4).encode())
        return

    async def handle_startpropose(self, client, msg: StartPropose):
        await client.sendall(b"#")
        if msg.debug:
            self.debug = True
        await curio.spawn(self.run_instance, str(msg.value), msg.accs_idx, daemon=True)
        return

    async def handle_waitp1pausedreq(self, client, msg: WaitP1PausedReq):
        await self._p1_paused_evt.wait()
        await client.sendall(b"#")
        return

    async def handle_p1resumereq(self, client, msg: P1ResumeReq):
        if msg.p1_accs_idx:
            self._p1_accs_idx = list(msg.p1_accs_idx)
        if msg.p2_accs_idx:
            self._p2_accs_idx = list(msg.p2_accs_idx)
        await self._p1_resume_evt.set()
        await client.sendall(b"#")
        return

    async def handle_waitp2pausedreq(self, client, msg: WaitP2PausedReq):
        await self._p2_paused_evt.wait()
        await client.sendall(b"#")
        return

    async def handle_p2resumereq(self, client, msg: P2ResumeReq):
        if msg.p1_accs_idx:
            self._p1_accs_idx = list(msg.p1_accs_idx)
        if msg.p2_accs_idx:
            self._p2_accs_idx = list(msg.p2_accs_idx)
        await self._p2_resume_evt.set()
        await client.sendall(b"#")
        return

    def get_acceptors(self, accs_idx=None):
        acc_socks = self.acceptor_socks
        if accs_idx:
            acc_socks = [self.acceptor_socks[idx] for idx in accs_idx]
        return acc_socks

    async def p1(self, ballot_number=None, accs_idx=None):
        if ballot_number is None:
            ballot_number = self.get_ballot_number()
        propose_req = Proposal(ballot_number=ballot_number)
        propose_resps = []
        if self._p1_accs_idx:
            acc_socks = self.get_acceptors(self._p1_accs_idx)
        else:
            acc_socks = self.get_acceptors(accs_idx)
        for sock in acc_socks:
            await sock.sendall(propose_req.to_bytes())
        for sock in acc_socks:
            resp = await sock.recv(4096)
            propose_resps.append(Msg.from_str(resp))
        promised = []
        rejected = []
        for resp in propose_resps:
            if type(resp) == Promised:
                promised.append(resp)
            else:
                rejected.append(resp)
        return promised, rejected

    async def p2(self, ballot_number=None, value=None, accs_idx=None):
        if ballot_number is None:
            ballot_number = self.get_ballot_number()
        if self._p2_accs_idx:
            acc_socks = self.get_acceptors(self._p2_accs_idx)
        else:
            acc_socks = self.get_acceptors(accs_idx)
        accept_req = AcceptReq(ballot_number=ballot_number, value=str(value))
        resps = []
        for sock in acc_socks:
            await sock.sendall(accept_req.to_bytes())
        for sock in acc_socks:
            resp = await sock.recv(4096)
            resps.append(Msg.from_str(resp))
        succ, failed = [], []
        for resp in resps:
            if type(resp) == AcceptSucc and resp.ballot_number == self.last_bn:
                succ.append(resp)
            else:
                failed.append(resp)
        return succ, failed

    async def get_ballot_number(self):
        msg = GetBallotNumberReq(least=self.last_bn)
        await self.ballot_sock.sendall(msg.to_bytes())
        data = await self.ballot_sock.recv(4096)
        msg = GetBallotNumberResp.from_str(data)
        return msg.ballot_number

    async def run_instance(self, value, accs_idx):
        while True:
            self.last_bn = await self.get_ballot_number()
            print(f"{self.info} sending a proposal with a ballot number of {self.last_bn}")
            promised, rejected = await self.p1(self.last_bn, accs_idx)
            print(f"{self.info} got a propose response:")
            print(f"!promised: {promised}")
            print(f"@rejected: {rejected}")
            if self.debug:
                print(f"{self.info} paused at the end of p1")
                await self._p1_paused_evt.set()
                await self._p1_resume_evt.wait()
                print(f"{self.info} resumed from p1")
                self._p1_resume_evt.clear()
                self._p1_paused_evt.clear()
                if self._stopped.is_set():
                    # print(f"{self.info}._stopped was set, then return at p1")
                    return
            if len(promised) <= len(self.acceptor_socks) // 2:
                max_bn = max([i.ballot_number for i in rejected])
                self.last_bn = max_bn
                continue
            promised = sorted([i for i in promised if i.max_accepted_number is not None], key=lambda n: -n.max_accepted_number)
            if promised:
                print(f"{self.info} has to choose a candidate of {promised[0].value} associated "
                      f"with a ballot number {promised[0].max_accepted_number} "
                      f"over the value {value}")
                value = promised[0].value
            print(f"{self.info} sending accepet request, ballot_bumber {self.last_bn}")
            succ, failed = await self.p2(self.last_bn, value, accs_idx)
            print(f"{self.info} got an accept response:")
            print(f"#accepted {succ}")
            print(f"$rejected {failed}")
            if self.debug:
                print(f"{self.info} paused at end of p2")
                await self._p2_paused_evt.set()
                await self._p2_resume_evt.wait()
                print(f"{self.info} resumed from p2")
                self._p2_resume_evt.clear()
                self._p2_paused_evt.clear()
                if self._stopped.is_set():
                    # print(f"{self.info}._stopped was set, then return at p2")
                    return
            if len(succ) <= len(self.acceptor_socks) // 2:
                max_rejected_num = float("-inf")
                if failed:
                    max_rejected_num = max([i.ballot_number for i in failed])
                self.last_bn = max(max_rejected_num, self.last_bn)
                continue
            print(f"{self.info} successfuly proposed and wrote a value of {value}")
            self._chosen_val = value
            await self._chosen_evt.set()
            break
        return

    async def handle_waitchosenreq(self, client, msg: WaitChosenReq):
        await self._chosen_evt.wait()
        await client.sendall(str(self._chosen_val).encode())
        return


class Acceptor(Synod):
    
    def __init__(self, addr, port):
        super(Acceptor, self).__init__(addr, port)
        self.max_promised_bn = None
        self.max_accepted_bn = None
        self.max_accepted_val = None
        self.lock = curio.Lock()
        return

    @property
    def info(self):
        return f"Acceptor<{self.address},{self.max_promised_bn},{self.max_accepted_bn},{self.max_accepted_val}>"


    async def handle_showinfo(self, client, msg: ShowInfo):
        await client.sendall(self.info.encode())
        return

    async def handle_proposal(self, client, msg: Proposal):
        async with self.lock:
            if self.max_promised_bn is not None and self.max_promised_bn >= msg.ballot_number:
                # smaller ballot number, reject.
                # repeated proposal, reject.
                print(f"{self.info} rejected {msg}")
                msg = Rejected(ballot_number=self.max_promised_bn)
                await client.sendall(msg.to_bytes())
                return
            print(f"{self.info} promised {msg}")
            self.max_promised_bn = msg.ballot_number
            msg = Promised(max_accepted_number=self.max_accepted_bn, value=self.max_accepted_val)
            await client.sendall(msg.to_bytes())
        return

    async def handle_acceptreq(self, client, msg: AcceptReq):
        async with self.lock:
            if msg.ballot_number != self.max_promised_bn or msg.ballot_number == self.max_accepted_bn:
                # ballot number does not match, reject.
                # repeated accept request, reject.
                print(f"{self.info} rejected {msg}")
                await client.sendall(AcceptRejected(ballot_number=self.max_promised_bn).to_bytes())
                return
            print(f"{self.info} accepted {msg}")
            self.max_accepted_bn = msg.ballot_number
            self.max_accepted_val = msg.value
            await client.sendall(AcceptSucc(ballot_number=msg.ballot_number).to_bytes())
        return

    async def handle_learnreq(self, client, msg: LearnReq):
        await client.sendall(AccpetedInfo(max_accepted_bn=self.max_accepted_bn,
                                          value=self.max_accepted_val).to_bytes(),
                             )
        return


class Learner(Synod):

    def __init__(self, addr, port, acceptors_list):
        super(Learner, self).__init__(addr, port)
        self.acceptor_socks = []
        self.acceptors_list = acceptors_list
        self.info = f"Learner<{self.address}>"
        return

    async def spawn_and_wait(self):
        for address in self.acceptors_list:
            sock = socket(AF_INET, SOCK_STREAM)
            await sock.connect(address)
            self.acceptor_socks.append(sock)
        await super(Learner, self).spawn_and_wait()
        return

    async def handle_startlearn(self, client, msg: StartLearn):
        task = await curio.spawn(self.request_learn, daemon=True)
        msg = await task.join()
        await client.sendall(msg.to_bytes())
        return

    async def request_learn(self):
        msg = LearnResp()
        resps = []
        for sock in self.acceptor_socks:
            await sock.sendall(LearnReq().to_bytes())
        for sock in self.acceptor_socks:
            resp = await sock.recv(4096)
            resps.append(LearnResp.from_str(resp))
        print(f"{self.info} got response\n{resps}")
        max_accepted_bn = None
        for resp in resps:
            if resp.max_accepted_bn is None:
                continue
            if max_accepted_bn is None or resp.max_accepted_bn > max_accepted_bn:
                max_accepted_bn = resp.max_accepted_bn
        if max_accepted_bn is None:
            msg.msg = "no value has been written"
            return msg
        # a value that's chosen must be accepted by a majority of the acceptors in the same round.
        # or in other words, the chosen value must have been accepted by most of the acceptors with the same ballot number.
        max_resps = [resp for resp in resps if resp.max_accepted_bn == max_accepted_bn]
        if len(max_resps) <= len(self.acceptor_socks) // 2:
            msg.msg = "no value determined yet!"
            return msg
        msg.value = max_resps[0].value
        print(f"learned value {msg.value}")
        return msg


def main():
    acc = Acceptor("127.0.0.1", 1234)
    acc.run()
    return


if __name__ == "__main__":
    main()

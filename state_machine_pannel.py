

import json
import socket
import multiprocessing
import time
try:
    from prettyformatter import pprint
except:
    pprint = print

import messages

import state_machine

LOCAL_HOST = "127.0.0.1"


class ServerProcess:

    def __init__(self, server_list, server_idx, config=None):
        addr, port = server_list[server_idx]
        self.server = state_machine.StateMachine(addr, port, server_list, config)
        self.pro = None
        self.sock = None
        self.running = False
        return

    def __str__(self):
        return f"Server<{self.address}, running={self.running}>"

    def __repr__(self):
        return self.__str__()

    def wait_for_leader(self, forced=False):
        self.send_msg(state_machine.WaitForLeaderReq(forced=forced))
        return

    def get_leader_address(self):
        info = self.get_info()
        return tuple(info["leader_info"]["address"])

    def get_info(self):
        ret = self.send_msg(messages.ShowInfo())
        if not ret:
            return
        info = json.loads(ret)
        return info

    def get_brief_info(self, last_log_idx=1):
        info = self.get_info()
        if not info:
            return
        data = {"address": info["address"],
                "leader": info["leader_info"]["address"],
                "logs": info["logs"][:last_log_idx+1],
                "left_idx": info["left_idx"],
                "right_idx": info["right_idx"],
                }
        return data

    @property
    def address(self):
        return self.server.address

    def run(self):
        self.pro = multiprocessing.Process(target=self.server.run, daemon=True)
        self.pro.start()
        time.sleep(0.5)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.server.addr, self.server.port))
        self.running = True
        return

    def close(self):
        self.sock.sendall(messages.Close().to_bytes())
        self.sock.close()
        self.running = False
        self.sock = None
        return

    def send_msg(self, msg):
        if not self.running:
            return
        self.sock.sendall(msg.to_bytes())
        ret = self.sock.recv(4096)
        return ret.decode()


def run_servers(n=3, config_map=None) -> dict[tuple, ServerProcess]:
    server_list = [(LOCAL_HOST, 1234+i) for i in range(n)]
    svr_pros = {}
    for idx in range(0, len(server_list)):
        config = None
        if config_map:
            config = config_map.get(idx, None)
        pro = ServerProcess(server_list, idx, config)
        pro.run()
        svr_pros[pro.address] = pro
    return svr_pros


class ServersManager:

    def __init__(self, n=3, config_map=None):
        self.pros = run_servers(n, config_map)
        self.servers = list(self.pros.values())
        self.idx_servers = {i: j for i, j in enumerate(self.servers)}
        return

    def get_server_by_idx(self, idx) -> ServerProcess:
        return self.idx_servers[idx]

    def get_server_by_address(self, address) -> ServerProcess:
        return self.pros[address]

    def get_address(self, idx) -> tuple:
        return self.get_server_by_idx(idx).address

    def wait_for_leader(self, old_leader: ServerProcess =None):
        addresss = old_leader
        if old_leader:
            addresss = old_leader.address
        for s in self.servers:
            if not s.running:
                continue
            s.send_msg(state_machine.WaitForLeaderReq(old_leader=addresss))
        return

    def get_leader_address(self):
        laddress = None
        for s in self.servers:
            if not s.running:
                continue
            laddress = s.get_leader_address()
            break
        return laddress

    def get_leader_server(self):
        laddress = self.get_leader_address()
        pro = self.pros[laddress]
        return pro

    def get_followers(self):
        laddress = self.get_leader_address()
        followers = []
        for s in self.servers:
            if s.address == laddress:
                continue
            followers.append(s)
        return followers

    def get_info(self):
        ret = []
        for s in self.servers:
            if not s.running:
                continue
            ret.append(s.get_info())
        return ret

    def get_brief_info(self, last_log_idx=1):
        ret = []
        for s in self.servers:
            if not s.running:
                continue
            ret.append(s.get_brief_info(last_log_idx=last_log_idx))
        return ret


def get_followers(leader_addreess, servers_map: dict[tuple, ServerProcess]):
    followers = []
    for address, pro in servers_map.items():
        if address == leader_addreess:
            continue
        followers.append(pro)
    return followers


# ======================================


def write_a_value():
    m = ServersManager(3)
    m.wait_for_leader()
    leader = m.get_leader_server()
    resp = leader.send_msg(state_machine.WriteReq(value="123dsf"))
    print(resp)
    for i in m.get_brief_info():
        print(i)
    return


def partition_no_leader():
    m = ServersManager(3)
    m.wait_for_leader()
    leader1 = m.get_leader_server()
    print(f"leader1 {leader1}")
    for i in m.get_brief_info():
        print(i)
    leader1.close()
    print(f"!leader1 {leader1} closed")
    m.wait_for_leader(old_leader=leader1)
    leader2 = m.get_leader_server()
    print(f"leader2 {leader2}")
    resp = leader2.send_msg(state_machine.WriteReq(value="partition_case_one"))
    print(resp)
    for i in m.get_brief_info():
        print(i)
    print("-----------")
    leader1.run()
    print(f"!leader1 {leader1} comes back")
    for i in m.get_brief_info():
        print(i)
    resp = leader2.send_msg(state_machine.WriteReq(value="!!safdsg"))
    print(resp)
    for i in m.get_brief_info():
        print(i)
    print("----------")
    leader2.close()
    print(f"!leader2 {leader2} closed")
    m.wait_for_leader(old_leader=leader2)
    leader3 = m.get_leader_server()
    print(f"leader3 {leader3}")
    resp = leader3.send_msg(state_machine.WriteReq(value="111234t"))
    print(resp)
    for i in m.get_brief_info(2):
        print(i)
    input("$$$$$$$$$$$$$$$$$")
    return


def partition_working():
    m = ServersManager(5)
    m.wait_for_leader()
    leader1 = m.get_leader_server()
    print(f"leader1 {leader1}")
    followers = m.get_followers()
    for idx, i in enumerate(followers):
        print(f"{idx}: {i}")
    followers[0].send_msg(state_machine.Config(dead_nodes=[leader1.address]))
    followers[1].send_msg(state_machine.Config(dead_nodes=[leader1.address]))
    leader1.send_msg(state_machine.Config(dead_nodes=[followers[0].address, followers[1].address]))
    #
    time.sleep(5)
    leader1.send_msg(state_machine.Config(dead_nodes=[followers[2].address]))
    resp = leader1.send_msg(state_machine.WriteReq(value="age234235"))
    print(resp)
    print("leader should be not working++++++++++++++")
    time.sleep(3)
    leader1.send_msg(state_machine.Config(clear_dead_nodes=True))
    followers[0].send_msg(state_machine.Config(clear_dead_nodes=True))
    followers[1].send_msg(state_machine.Config(clear_dead_nodes=True))
    input("...")
    return


def main():
    write_a_value()
    # partition_no_leader()
    # partition_working()
    return


if __name__ == "__main__":
    main()

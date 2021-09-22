import sys
import uuid
import socket
import multi_paxos_msg
from concurrent.futures import ThreadPoolExecutor


class Client:

    def __init__(self, name, host, port):
        self.host, self.port = host, port
        self.sock = socket.socket()
        self.sock.settimeout(10*2)
        self.sock.connect((host, port))
        self.name = "Client<%s>" % name
        self.pool = ThreadPoolExecutor(5)
        return

    def get_req_id(self):
        return str(uuid.uuid1())

    def run(self):
        while True:
            cmd = input("...\n")
            if not cmd:
                continue
            cmd = cmd.split(" ")
            if cmd[0] == "batch_choose":
                value1, value2 = cmd[1], cmd[2]
                cmd1 = ["choose", value1]
                cmd2 = ["choose", value2]
                req_id1 = self.get_req_id()
                req_id2 = self.get_req_id()
                self.pool.submit(self.extract_input_and_send, cmd1, req_id1, True)
                self.pool.submit(self.extract_input_and_send, cmd2, req_id2, True)
                continue
            self.pool.submit(self.extract_input_and_send, cmd)
        return

    def extract_input_and_send(self, cmd, req_id=None, new_con=False):
        data_bytes = b""
        if cmd[0] == "choose":
            value = cmd[1]
            msg = self.choose(value, req_id)
        elif cmd[0] == "info":
            msg = self.info()
        elif cmd[0] == "get_log_data":
            min_index, max_index = cmd[1].split(",")
            min_index = int(min_index)
            max_index = int(max_index)
            msg = self.get_log_data(min_index, max_index)
        elif cmd[0] == "disable_ld":
            flag = int(cmd[1].strip())
            msg = self.disable_leadership(flag)
        elif cmd[0] == "ignore_accept":
            flag = int(cmd[1].strip())
            msg = self.ignore_accept(flag)
        elif cmd[0] == "disable_pong":
            flag = int(cmd[1].strip())
            msg = self.disbable_pong(flag)
        elif cmd[0] == "get_retry_accept":
            msg = self.get_retry_accept()
        else:
            print("no impl for cmd", cmd[0])
            return
        self.send_msg(msg, cmd, self.sock if new_con is False else None)
        return

    def send_msg(self, msg, cmd, s):
        msg.set_from_node(self.name)
        data_bytes = msg.get_bytes()
        if s is None:
            print("new connection!")
            s = socket.socket()
            s.settimeout(10*2)
            s.connect((self.host, self.port))
        s.sendall(data_bytes)
        suc = False
        try:
            rec = s.recv(multi_paxos_msg.IOMSG_FIX_LEN)
        except socket.timeout:
            print("Didn't receive data! [Timeout]")
        else:
            print("%s resp" % cmd, rec.decode().strip("0"))
            if rec == b"":
                suc = False
            else:
                suc = True
        if not suc:
            print("cmd %s fail, return" % cmd)
            self.sock.close()
            return
        return

    def info(self):
        msg = multi_paxos_msg.ClientNodeInfoCmd()
        msg.set_info_key("all")
        return msg

    def choose(self, value, req_id=None):
        choose_msg = multi_paxos_msg.ClientChooseCmd()
        choose_msg.set_value(value)
        choose_msg.set_req_id(req_id or self.get_req_id())
        print("choose req_id", choose_msg.req_id)
        return choose_msg

    def get_log_data(self, min_index, max_index):
        msg = multi_paxos_msg.ClientGetLogDataCMD()
        msg.set_index(min_index, max_index)
        return msg

    def disable_leadership(self, flag):
        msg = multi_paxos_msg.ClientDisableLeadershipCMD()
        msg.set_flag(flag)
        return msg

    def ignore_accept(self, flag):
        msg = multi_paxos_msg.ClientIgnoreAcceptCMD()
        msg.set_flag(flag)
        return msg

    def disbable_pong(self, flag):
        msg = multi_paxos_msg.ClientDisablePongCMD()
        msg.set_flag(flag)
        return msg

    def get_retry_accept(self):
        msg = multi_paxos_msg.ClientGetRetryAcceptListCMD()
        return msg


def main():
    node_id = 1
    if len(sys.argv) >= 2:
        node_id = int(sys.argv[1])
    node_map = {1: 6666, 2: 6667, 3: 6668, 4: 6669, 5: 6670, 6: 6671}
    client = Client("alpha", "127.0.0.1", node_map[node_id])
    client.run()
    return

if __name__ == "__main__":
    main()

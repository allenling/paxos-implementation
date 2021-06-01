import sys
import uuid
import socket
from multi_paxos import ClientChooseCmd, ClientNodeInfoCmd, ClientGetLogDataCMD, IOMSG_FIX_LEN, ClientDisableLeadershipCMD


class Client:

    def __init__(self, name, host, port):
        self.host, self.port = host, port
        self.sock = socket.socket()
        self.sock.settimeout(10*2)
        self.sock.connect((host, port))
        self.name = "Client<%s>" % name
        return

    def get_req_id(self):
        return str(uuid.uuid1())

    def run(self):
        while True:
            cmd = input("...\n")
            cmd = cmd.split(" ")
            data_bytes = b""
            if cmd[0] == "choose":
                value = cmd[1]
                msg = self.choose(value)
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
            else:
                print("no impl for cmd", cmd[0])
                continue
            msg.set_from_node(self.name)
            data_bytes = msg.get_bytes()
            self.sock.sendall(data_bytes)
            suc = False
            try:
                rec = self.sock.recv(IOMSG_FIX_LEN)
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
        msg = ClientNodeInfoCmd()
        msg.set_info_key("all")
        return msg

    def choose(self, value):
        choose_msg = ClientChooseCmd()
        choose_msg.set_value(value)
        choose_msg.set_req_id(str(uuid.uuid1()))
        print("choose req_id", choose_msg.req_id)
        return choose_msg

    def get_log_data(self, min_index, max_index):
        msg = ClientGetLogDataCMD()
        msg.set_index(min_index, max_index)
        return msg

    def disable_leadership(self, flag):
        msg = ClientDisableLeadershipCMD()
        msg.set_flag(flag)
        return msg


def main():
    node_id = 2
    if len(sys.argv) >= 2:
        node_id = int(sys.argv[1])
    node_map = {1: 6666, 2: 6667, 3: 6668}
    client = Client("alpha", "127.0.0.1", node_map[node_id])
    client.run()
    return

if __name__ == "__main__":
    main()

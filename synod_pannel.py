
import socket

import multiprocessing
import time

import messages
import synod_protocol


LOCAL_ADDR = "127.0.0.1"


class SynodPro:

    def __init__(self, obj: synod_protocol.Synod):
        self.obj = obj
        self.pro = None
        self.sock = None
        return

    @property
    def addr(self):
        return self.obj.addr

    @property
    def port(self):
        return self.obj.port

    @property
    def address(self):
        return self.obj.address

    def run(self):
        # run in process
        self.pro = multiprocessing.Process(target=self.obj.run, daemon=True)
        self.pro.start()
        time.sleep(0.1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.obj.addr, self.obj.port))
        return

    def close(self):
        self.sock.sendall(synod_protocol.Close().to_bytes())
        self.sock.close()
        return

    def send_msg(self, msg):
        self.sock.sendall(msg.to_bytes())
        ret = self.sock.recv(4096)
        return ret.decode()


def get_acceptors_address(port=1235, nums=3):
    return [(LOCAL_ADDR, i) for i in range(port, port+nums)]


def start_ballot_number_server(port=1233):
    ballot_pro = SynodPro(synod_protocol.BallotNumberServer(LOCAL_ADDR, port))
    ballot_pro.run()
    return ballot_pro


def start_acceptors(nums=3):
    acceptors = []
    addresses_list = get_acceptors_address(nums=nums)
    for addr, port in addresses_list:
        acceptor = synod_protocol.Acceptor(addr, port)
        acc_pro = SynodPro(acceptor)
        acc_pro.run()
        acceptors.append(acc_pro)
    return acceptors, addresses_list


def start_proposer(acceptors_list, ballot_address, port=1234):
    pro = SynodPro(synod_protocol.Proposer(LOCAL_ADDR, port, acceptors_list, ballot_address))
    pro.run()
    return pro


def start_leaner(acceptors_list, port):
    pro = SynodPro(synod_protocol.Learner(LOCAL_ADDR, port, acceptors_list))
    pro.run()
    return pro


# =============================


def accept_succ():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    proposer = start_proposer(acceptors_list, ballot_server.address)
    proposer.send_msg(synod_protocol.StartPropose(value="100"))
    ret = proposer.send_msg(messages.WaitChosenReq())
    print(f"proposer has chosen value {ret}")
    learner = start_leaner(acceptors_list, port=10010)
    ret = learner.send_msg(synod_protocol.StartLearn())
    print(f"learner returned {ret}")
    ballot_server.close()
    proposer.close()
    learner.close()
    for acc in acceptors:
        acc.close()
    return


def live_lock_example():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    p1 = start_proposer(acceptors_list, ballot_server.address)
    p2 = start_proposer(acceptors_list, ballot_server.address, port=1440)
    p1.send_msg(messages.StartPropose(value="p1_value", debug=True))
    p1.send_msg(messages.WaitP1PausedReq())
    p2.send_msg(messages.StartPropose(value="p2_value", debug=True))
    p2.send_msg(messages.WaitP1PausedReq())
    #
    p1.send_msg(messages.P1ResumeReq())
    p1.send_msg(messages.P2ResumeReq())
    p1.send_msg(messages.WaitP1PausedReq())
    #
    p2.send_msg(messages.P1ResumeReq())
    p2.send_msg(messages.P2ResumeReq())
    p2.send_msg(messages.WaitP1PausedReq())
    #
    print("=========> nodes info:")
    ret = p1.send_msg(messages.ShowInfo())
    print(ret)
    ret = p2.send_msg(messages.ShowInfo())
    print(ret)
    for acc in acceptors:
        ret = acc.send_msg(messages.ShowInfo())
        print(ret)
    ballot_server.close()
    p1.close()
    p2.close()
    for acc in acceptors:
        acc.close()
    return


def the_chosen_over_your_value():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    p1 = start_proposer(acceptors_list, ballot_server.address)
    p1.send_msg(messages.StartPropose(value="p1_value", accs_idx=[0, 1]))
    ret = p1.send_msg(messages.WaitChosenReq())
    print(f"p1 has chosen value {ret}")
    #
    p2 = start_proposer(acceptors_list, ballot_server.address, port=1440)
    p2.send_msg(messages.StartPropose(value="p2_value"))
    ret = p2.send_msg(messages.WaitChosenReq())
    print(f"p2 has chosen value {ret}")
    print("=========> nodes info:")
    ret = p1.send_msg(messages.ShowInfo())
    print(ret)
    ret = p2.send_msg(messages.ShowInfo())
    print(ret)
    for acc in acceptors:
        ret = acc.send_msg(messages.ShowInfo())
        print(ret)
    ballot_server.close()
    p1.close()
    p2.close()
    for acc in acceptors:
        acc.close()
    return


def candidate_over_your_value():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    p1 = start_proposer(acceptors_list, ballot_server.address)
    p1.send_msg(messages.StartPropose(value="p1_value", debug=True))
    p1.send_msg(messages.WaitP1PausedReq())
    p1.send_msg(messages.P1ResumeReq(p2_accs_idx=[0]))
    p1.send_msg(messages.WaitP2PausedReq())
    # at this time, p1 just got response from only one acceptor, which is the first one, meaning
    # p1_value will not be the chosen one.
    # but this p1_value will be the candidate to write, or the value to be accpeted for p2 if p2 is maintaining
    # a connection with the first acceptor.
    p2 = start_proposer(acceptors_list, ballot_server.address, port=1440)
    p2.send_msg(messages.StartPropose(value="p2_value"))
    ret = p2.send_msg(messages.WaitChosenReq())
    print(f"p2 has chosen value {ret}")
    print("=========> nodes info:")
    ret = p1.send_msg(messages.ShowInfo())
    print(ret)
    ret = p2.send_msg(messages.ShowInfo())
    print(ret)
    for acc in acceptors:
        ret = acc.send_msg(messages.ShowInfo())
        print(ret)
    ballot_server.close()
    p1.close()
    p2.close()
    for acc in acceptors:
        acc.close()
    return


def no_candidate_detected():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    p1 = start_proposer(acceptors_list, ballot_server.address)
    p1.send_msg(messages.StartPropose(value="p1_value", debug=True))
    p1.send_msg(messages.WaitP1PausedReq())
    p1.send_msg(messages.P1ResumeReq(p2_accs_idx=[0]))
    p1.send_msg(messages.WaitP2PausedReq())
    #
    p2 = start_proposer(acceptors_list, ballot_server.address, port=1440)
    p2.send_msg(messages.StartPropose(value="p2_value", accs_idx=[1, 2]))
    ret = p2.send_msg(messages.WaitChosenReq())
    print(f"p2 has chosen value {ret}")
    learner = start_leaner(acceptors_list, port=10010)
    ret = learner.send_msg(synod_protocol.StartLearn())
    print(f"learner returned {ret}")
    print("=========> nodes info:")
    ret = p1.send_msg(messages.ShowInfo())
    print(ret)
    ret = p2.send_msg(messages.ShowInfo())
    print(ret)
    for acc in acceptors:
        ret = acc.send_msg(messages.ShowInfo())
        print(ret)
    ballot_server.close()
    p1.close()
    p2.close()
    for acc in acceptors:
        acc.close()
    return


def value_accepted_in_two_rounds():
    ballot_server = start_ballot_number_server()
    acceptors, acceptors_list = start_acceptors()
    p1 = start_proposer(acceptors_list, ballot_server.address)
    p1.send_msg(messages.StartPropose(value="p1_value", debug=True))
    p1.send_msg(messages.WaitP1PausedReq())
    p1.send_msg(messages.P1ResumeReq(p2_accs_idx=[0]))
    p1.send_msg(messages.WaitP2PausedReq())
    #
    p2 = start_proposer(acceptors_list, ballot_server.address, port=1440)
    p2.send_msg(messages.StartPropose(value="p2_value", debug=True))
    p2.send_msg(messages.P1ResumeReq(p2_accs_idx=[1]))
    p2.send_msg(messages.WaitP2PausedReq())
    # the value is accepted by a majority of acceptors, but in two different rounds!
    # so the value should not be the chosen one right now.
    for acc in acceptors:
        ret = acc.send_msg(messages.ShowInfo())
        print(ret)
    learner = start_leaner(acceptors_list, port=10010)
    ret = learner.send_msg(synod_protocol.StartLearn())
    print(f"learner returned {ret}")
    # we have to make sure that the candidate is being accepted so that the candidacate becomes the chosen one.
    p3 = start_proposer(acceptors_list, ballot_server.address, port=1441)
    p3.send_msg(messages.StartPropose(value="p3_value"))
    ret = p3.send_msg(messages.WaitChosenReq())
    print(f"p3 has chosen value {ret}")
    learner = start_leaner(acceptors_list, port=10010)
    ret = learner.send_msg(synod_protocol.StartLearn())
    print(f"learner returned {ret}")
    #
    learner.close()
    ballot_server.close()
    p1.close()
    p2.close()
    p3.close()
    for acc in acceptors:
        acc.close()
    return


def main():
    # accept_succ()
    # live_lock_example()
    # the_chosen_over_your_value()
    # candidate_over_your_value()
    # no_candidate_detected()
    value_accepted_in_two_rounds()
    return


if __name__ == "__main__":
    main()

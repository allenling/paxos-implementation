import time
import requests
from concurrent.futures import ThreadPoolExecutor
from http_utils import DispatchServer
from threading import Event
import enum


def get_even_yielder():
    num = 0
    while True:
        yield num
        num += 2
    return


def get_odd_yielder():
    num = 1
    while True:
        yield num
        num += 2
    return


def send_to_acceptors(acceptor_requests):
    res = []
    for name, path, data in acceptor_requests:
        try:
            resp = requests.post(path, json=data)
        except requests.Timeout:
            print("send acceptor %s(%s) %s timeout" % (name, path, data))
        except requests.exceptions.ConnectionError:
            print("send acceptor %s(%s) %s close connection" % (name, path, data))
        else:
            if resp.status_code == 200:
                res.append(resp.json())
            else:
                print("send acceptor %s(%s) %s get status code" % (name, path, resp.status_code))
    return res


def get_default_set_event():
    evt = Event()
    evt.set()
    return evt


class ProposerState(enum.Enum):
    START_PREPARATION = 0
    PRE_ACCEPT = 10
    START_ACCEPTING = 20


class Proposer:

    def __init__(self, name, acceptors_nums, acceptor_map, proposer_number_yielder):
        self.name = name
        self.proposer_number_yielder = proposer_number_yielder
        self.acceptor_map = acceptor_map
        self.acceptors_nums = acceptors_nums
        self.majority = self.acceptors_nums // 2 + 1
        self.pre_accept_event = get_default_set_event()
        self.status = None
        return

    def get_next_proposal_number(self, greater=-1):
        res = next(self.proposer_number_yielder)
        while res <= greater:
            res = next(self.proposer_number_yielder)
        return res

    def choose(self, value):
        print("Proposer %s is going to choose %s" % (self.name, value))
        min_pn = -1
        while True:
            self.status = ProposerState.START_PREPARATION
            pn, value = self.prepare(value, min_pn)  # this value may not equals that passed value
            min_pn = pn
            self.status = ProposerState.PRE_ACCEPT
            if not self.pre_accept_event.is_set():
                print("?????????? Proposer %s wait for pre_accept_event!" % self.name)
            self.pre_accept_event.wait()
            self.status = ProposerState.START_ACCEPTING
            accepted, min_pn = self.accept(pn, value)
            if accepted:
                break
        return

    def prepare(self, value, min_pn):
        """
        try to get promises from the majority of acceptors
        """
        while True:
            pn = self.get_next_proposal_number(greater=min_pn)
            min_pn = pn
            data = {"pn": pn, "proposer": self.name}
            prepare_request_info = [[acceptr_name, acceptor_url + "/prepare", data] for acceptr_name,acceptor_url in
                                    self.acceptor_map.items()]
            resps = send_to_acceptors(prepare_request_info)
            success_resps = [i for i in resps if i["status"] == "success"]
            max_prepare_pn = max([i["prepare_pn"] for i in resps if "prepare_pn" in i], default=min_pn)
            if len(success_resps) < self.majority:
                min_pn = max_prepare_pn
                print("Proposer %s prepare %s cant get promises from majority of acceptors, retry" % (self.name, pn))
                print("Proposer %s choose min_pn %s to accelerate preparation" % (self.name, min_pn))
                continue
            print("Proposer %s prepare %s get promises from majority of acceptors, check accepted value" % (self.name, pn))
            max_accepted_pn, max_accepted_value = float("-inf"), value
            for i in resps:
                if i["accepted_pn"] and i["accepted_pn"] > max_accepted_pn:
                    max_accepted_pn, max_accepted_value = i["accepted_pn"], i["accepted_value"]
            if max_accepted_pn != float("-inf"):
                print("Proposer %s abandon original value %s, choose already accepted value %s"
                      % (self.name, value, max_accepted_value))
            else:
                print("Proposer %s choose original value %s" % (self.name, max_accepted_value))
            break
        return pn, max_accepted_value

    def accept(self, pn, value):
        data = {"value": value, "pn": pn, "proposer": self.name}
        accept_request_info = [[acceptr_name, acceptor_url + "/accept", data] for acceptr_name,acceptor_url in
                               self.acceptor_map.items()]
        resps = send_to_acceptors(accept_request_info)
        success_resps = [i for i in resps if i["status"] == "success"]
        max_prepare_pn = max([i["prepare_pn"] for i in resps if "prepare_pn" in i], default=pn)
        accepted = True
        if len(success_resps) < self.majority:
            print("Proposer %s accept %s %s cant get acceptances from get majority of nodes, max_prepare_pn %s"
                  % (self.name, pn, value, max_prepare_pn))
            accepted = False
        else:
            print("########## Proposer %s choose %s %s success!" % (self.name, pn, value))
        return accepted, max_prepare_pn


class Acceptor:

    def __init__(self, name, port):
        self.name = name
        self.prepare_pn = -1
        self.accepted_pn = None
        self.accepted_value = None
        self.port = port
        return

    def prepare(self, data):
        status = "success"
        if data["pn"] <= self.prepare_pn:
            print("Acceptor %s(%s, %s, %s) reject prepare request %s" % (self.name,
                                                                         self.prepare_pn,
                                                                         self.accepted_pn,
                                                                         self.accepted_value,
                                                                         data,
                                                                         )
                  )
            status = "fail"
        else:
            print("Acceptor %s(%s, %s, %s) promise prepare %s" % (self.name,
                                                                  self.prepare_pn,
                                                                  self.accepted_pn,
                                                                  self.accepted_value,
                                                                  data,
                                                                  )
                  )
            self.prepare_pn = data["pn"]
        resp = {"acceptor": self.name, "prepare_pn": self.prepare_pn,
                "accepted_pn": self.accepted_pn,
                "accepted_value": self.accepted_value,
                "status": status,
                }
        return resp


    def accept(self, data):
        status = "success"
        if data["pn"] < self.prepare_pn:
            print("Acceptor %s(%s, %s, %s) reject accept request %s" % (self.name,
                                                                        self.prepare_pn,
                                                                        self.accepted_pn,
                                                                        self.accepted_value,
                                                                        data,
                                                                        )
                  )
            status = "fail"
        else:
            print("=====> Acceptor %s(%s, %s, %s) accept %s" % (self.name,
                                                                self.prepare_pn,
                                                                self.accepted_pn,
                                                                self.accepted_value,
                                                                data,
                                                                )
                  )
            self.prepare_pn = data["pn"]  # must update prepare proposal number!
            self.accepted_pn = data["pn"]
            self.accepted_value = data["value"]
        resp = {"acceptor": self.name, "prepare_pn": self.prepare_pn,
                "accepted_pn": self.accepted_pn,
                "accepted_value": self.accepted_value,
                "status": status,
                }
        return resp

    def run(self):
        self.server = DispatchServer("Acceptor<%s>" % self.name, self.port)
        self.server.set_path("prepare", self.prepare)
        self.server.set_path("accept", self.accept)
        self.server.start()
        print("Acceptor %s run return" % self.name)
        return

    def shutdown(self):
        self.server.shutdown()
        return


# =================================

class Example:

    def start_acceptors(self):
        ports = [6666, 6667, 6668, 6669, 7000]
        self.acceptors = [Acceptor("A<%s>" % index, port) for index, port in enumerate(ports)]
        self.acceptor_executor = ThreadPoolExecutor(max_workers=len(ports))
        for i in self.acceptors:
            self.acceptor_executor.submit(i.run)
        time.sleep(1)
        self.acceptor_map = {obj.name: "http://localhost:%s" % obj.port for obj in self.acceptors}
        return

    def run_basic_paxos_one_proposer(self):
        self.start_acceptors()
        odd_proposer = Proposer("odd_proposer", 5, self.acceptor_map, get_odd_yielder())
        odd_proposer.choose("red")
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return

    def run_example_for_acceleration_preparation(self):
        self.start_acceptors()
        odd_proposer = Proposer("odd_proposer", 5, self.acceptor_map, get_odd_yielder())
        odd_proposer.choose("red")
        odd1_proposer = Proposer("odd_proposer1", 5, self.acceptor_map, get_odd_yielder())
        odd1_proposer.choose("red1")
        odd2_proposer = Proposer("odd_proposer2", 5, self.acceptor_map, get_odd_yielder())
        odd2_proposer.choose("red2")
        even_proposer = Proposer("even_proposer", 5, self.acceptor_map, get_even_yielder())
        even_proposer.choose("blue")
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return

    def run_case_one(self):
        """
        chosen one cant be changed
        """
        self.start_acceptors()
        odd_proposer = Proposer("odd_proposer", 5, self.acceptor_map, get_odd_yielder())
        odd_proposer.choose("red")
        even_proposer = Proposer("even_proposer", 5, self.acceptor_map, get_even_yielder())
        even_proposer.choose("blue")
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return

    def run_case_two(self):
        """
        larger proposal number reject smaller proposal number
        """
        self.start_acceptors()
        odd_proposer = Proposer("odd_proposer", 5, self.acceptor_map, get_odd_yielder())
        even_proposer = Proposer("even_proposer", 5, self.acceptor_map, get_even_yielder())
        odd_proposer.pre_accept_event.clear()
        proposer_executor = ThreadPoolExecutor(max_workers=1)
        proposer_executor.submit(odd_proposer.choose, "red")
        while True:
            if odd_proposer.status == ProposerState.PRE_ACCEPT:
                break
            time.sleep(1)
        even_proposer.choose("blue")
        odd_proposer.pre_accept_event.set()  # red covered by blue
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return

    def run_case_two_one(self):
        """
        larger proposal number reject smaller proposal number
        and this time, we only send request to the majority of acceptors, not all of acceptors
        """
        self.start_acceptors()
        odd_proposer_acceptor_map = {obj.name: "http://localhost:%s" % obj.port for obj in self.acceptors[:3]}
        odd_proposer = Proposer("odd_proposer", 5, odd_proposer_acceptor_map, get_odd_yielder())
        even_proposer_acceptor_map = {obj.name: "http://localhost:%s" % obj.port for obj in self.acceptors[2:]}
        even_proposer = Proposer("even_proposer", 5, even_proposer_acceptor_map, get_even_yielder())
        odd_proposer.pre_accept_event.clear()
        proposer_executor = ThreadPoolExecutor(max_workers=1)
        proposer_executor.submit(odd_proposer.choose, "red")
        while True:
            if odd_proposer.status == ProposerState.PRE_ACCEPT:
                break
            time.sleep(1)
        even_proposer.choose("blue")
        odd_proposer.pre_accept_event.set()  # red covered by blue
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return

    def run_case_three(self):
        """
        """
        self.run_case_two_one()
        return

    def run_case_four(self):
        """
        no one can chose a value!
        they are in a dead cycle, no one can break out!
        """
        self.start_acceptors()
        odd_proposer_acceptor_map = {obj.name: "http://localhost:%s" % obj.port for obj in self.acceptors[:3]}
        odd_proposer = Proposer("odd_proposer", 5, odd_proposer_acceptor_map, get_odd_yielder())
        even_proposer_acceptor_map = {obj.name: "http://localhost:%s" % obj.port for obj in self.acceptors[2:]}
        even_proposer = Proposer("even_proposer", 5, even_proposer_acceptor_map, get_even_yielder())
        odd_proposer.pre_accept_event.clear()
        even_proposer.pre_accept_event.clear()
        proposer_executor = ThreadPoolExecutor(max_workers=2)
        proposer_executor.submit(odd_proposer.choose, "red")
        while True:
            if odd_proposer.status == ProposerState.PRE_ACCEPT:
                break
            time.sleep(1)
        proposer_executor.submit(even_proposer.choose, "blue")
        while True:
            if even_proposer.status == ProposerState.PRE_ACCEPT:
                break
            time.sleep(1)
        # here, we have odd=1, even=2
        while True:
            odd_proposer.pre_accept_event.set()
            while True:
                if odd_proposer.status == ProposerState.START_ACCEPTING:
                    break
                time.sleep(1)
            odd_proposer.pre_accept_event.clear()
            while True:
                if odd_proposer.status == ProposerState.PRE_ACCEPT:
                    break
                time.sleep(1)
            # odd=3, 5, 7, 9, ...
            even_proposer.pre_accept_event.set()
            while True:
                if even_proposer.status == ProposerState.START_ACCEPTING:
                    break
                time.sleep(1)
            even_proposer.pre_accept_event.clear()
            while True:
                if even_proposer.status == ProposerState.PRE_ACCEPT:
                    break
                time.sleep(1)
            # even=4, 6, 8, 10, ....
        input("....\n")
        for i in self.acceptors:
            i.shutdown()
        return


def main():
    # Example().run_basic_paxos_one_proposer()
    # Example().run_example_for_acceleration_preparation()
    # Example().run_case_one()
    # Example().run_case_two()
    # Example().run_case_two_one()
    Example().run_case_four()
    return


if __name__ == "__main__":
    main()
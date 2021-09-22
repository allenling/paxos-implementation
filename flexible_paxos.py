import sys
import curio
import multi_paxos_msg
from multi_paxos import LogStateMatchine, Config
from common import logger


class FlexibleMajoritySelector:

    def __init__(self, node_names):
        self.node_names = node_names.copy()
        return

    def _set_quorums(self):
        self.q1_nums = len(self.node_names) // 2 + 1  # 4 nodes, then we have Q1, 3 // 2 + 1 = 2, 2 + 1 = 3
        self.q2_nums = len(self.node_names) // 2  # 4 nodes, then we have Q2, 3 // 2 = 1, 1 + 1 = 2
        return

    def get_Q1_recipients(self):
        return self.node_names

    def get_Q2_recipients(self):
        return self.node_names

    def check_Q1_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.q1_nums

    def check_Q2_quorum(self, nodes: list):
        return len(nodes) >= self.q2_nums


class FlexibleSimpleSelector:

    def __init__(self, node_names):
        self.node_names = node_names.copy()
        return

    def _set_quorums(self):
        self.q1_nums = len(self.node_names) - 1
        self.q2_nums = 1
        return

    def get_Q1_recipients(self):
        return self.node_names

    def get_Q2_recipients(self):
        return self.node_names

    def check_Q1_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.q1_nums

    def check_Q2_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.q2_nums


class FlexibleGridSelector:

    def __init__(self, node_names):
        self.node_names = node_names.copy()
        return

    def set_grid(self, grid, node_id):
        self.node_id = node_id
        self.row_nodes = [i.copy() for i in grid]
        self.node_to_row = {}
        self.node_to_col = {}
        self.col_nodes = {i: [] for i in range(len(self.row_nodes[0]))}
        for rindex, row in enumerate(self.row_nodes):
            for cindex, v in enumerate(row):
                self.node_to_col[v] = cindex
                self.node_to_row[v] = rindex
                self.col_nodes[cindex].append(v)
        myrow, mycol = self.node_to_row[self.node_id], self.node_to_col[self.node_id]
        self.q1_nodes = self.row_nodes[myrow]  # all nodes in the same row
        self.q1_nodes.remove(self.node_id)
        self.q1_nodes_set = set(self.q1_nodes)
        self.q2_nodes = self.col_nodes[mycol]  # all nodes in the same col
        self.q2_nodes.remove(self.node_id)
        self.q2_nodes_set = set(self.q2_nodes)
        self.q1_nums = len(self.q1_nodes)
        self.q2_nums = len(self.q2_nodes)
        return

    def _set_quorums(self):
        return

    def get_Q1_recipients(self):
        # NOTE: we do not have to send prepare msg to all of nodes!
        return self.q1_nodes

    def get_Q2_recipients(self):
        return self.q2_nodes

    def check_Q1_quorum(self, nodes: list) -> bool:
        return set(nodes).issuperset(self.q1_nodes_set)

    def check_Q2_quorum(self, nodes: list):
        return set(nodes).issuperset(self.q2_nodes_set)


def test_flexible_majority():
    nodes = [2, 3, 4, 5, 6]  # my id is 1
    x = FlexibleMajoritySelector(nodes)
    print(x.name, x.get_Q1_recipients(), x.get_Q2_recipients())
    n1 = [2, 3, 4]
    print(x.check_Q1_quorum(n1))
    n1 = [2, 3]
    print(x.check_Q1_quorum(n1))
    n2 = [2, 3]
    print(x.check_Q2_quorum(n2))
    n2 = [2]
    print(x.check_Q2_quorum(n2))
    return

def test_flexible_simple():
    nodes = [2, 3, 4, 5, 6]  # my id is 1
    x = FlexibleSimpleSelector(nodes)
    print(x.name, x.get_Q1_recipients(), x.get_Q2_recipients())
    n1 = [2, 3, 4, 5]
    print(x.check_Q1_quorum(n1))
    n1 = [2, 3, 4]
    print(x.check_Q1_quorum(n1))
    n2 = [2]
    print(x.check_Q2_quorum(n2))
    return


def test_flexible_grid():
    nodes = [2, 3, 4, 5, 6]  # my id is 1
    rows = [[1, 2, 3],
            [4, 5, 6]]
    cols = [[1, 4],
            [2, 5],
            [3, 6],
            ]
    x = FlexibleGridSelector(nodes)
    for i in rows:
        print(i)
    for i in range(1, 7):
        print(f"my id {i}")
        x.set_grid(rows, i)
        q1, q2 = x.get_Q1_recipients(), x.get_Q2_recipients()
        print(f"q1: {q1}, q2: {q2}")
        n = q1[:1]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = q1
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = list(set(q1 + q2))
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = rows[0]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = rows[1]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = rows[0] + rows[1]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = cols[0]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = cols[1]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        n = cols[2]
        print(n, x.check_Q1_quorum(n), x.check_Q2_quorum(n))
        print("===============")
    return


class FPaxos(LogStateMatchine):

    def __init__(self, my_id, conf):
        super(FPaxos, self).__init__(my_id, conf)
        self.verbose_name = f"FPaxos<{self.node_name}>"
        return

    def _set_quorums(self):
        self.quorum_strategy = self.conf["quorum_strategy"]
        if self.quorum_strategy == "majority":
            assert len(self.conf["nodes"]) % 2 == 0
            self.quorum_selector_instance = FlexibleMajoritySelector(self.node_names)
        elif self.quorum_strategy == "simple":
            self.quorum_selector_instance = FlexibleSimpleSelector(self.node_names)
        elif self.quorum_strategy == "grid":
            self.quorum_selector_instance = FlexibleGridSelector(self.node_names)
            self.quorum_selector_instance.set_grid(self.conf["grid"], self.node_name)
        logger.info(f"{self.quorum_strategy} {self.quorum_selector_instance.__class__.__name__}")
        logger.info(f"Q1: {self.quorum_selector_instance.get_Q1_recipients()}")
        logger.info(f"Q2: {self.quorum_selector_instance.get_Q2_recipients()}")
        return

    def get_Q1_recipients(self):
        return self.quorum_selector_instance.get_Q1_recipients()

    def get_Q2_recipients(self):
        return self.quorum_selector_instance.get_Q2_recipients()

    def check_Q1_quorum(self, nodes: list) -> bool:
        return self.quorum_selector_instance.check_Q1_quorum(nodes)

    def check_Q2_quorum(self, nodes: list) -> bool:
        return self.quorum_selector_instance.check_Q2_quorum(nodes)

    async def check_state(self):
        healthy, unhealthy = multi_paxos_msg.ClusterState.healthy, multi_paxos_msg.ClusterState.unhealthy
        while not self._stop:
            await curio.sleep(multi_paxos_msg.NODE_TIMEOUT)
            online_nodes = self.gossip_msg.update_nodes_status()
            online_node_ids = [i[0] for i in online_nodes]
            lost_q1 = not self.check_Q1_quorum(online_node_ids)
            lost_q2 = not self.check_Q2_quorum(online_node_ids)
            # logger.info(f"{self.quorum_selector_instance.q1_nums} {self.quorum_selector_instance.q2_nums} {len(online_nodes)} "
            #             f"{lost_q1} {lost_q2}")
            if lost_q1 and lost_q2:
                if self.cluster_state == healthy:
                    self.cluster_state = unhealthy
                logger.info("i am on unhealty state because i've lost Q1 and Q2!!!!!!")
                continue
            elif not lost_q1 and not lost_q2:
                if self.cluster_state == unhealthy:
                    self.cluster_state = healthy
                    logger.info("i switch to healty state, both of Q1 and Q2 are good!!!!!!")
            if self.gossip_msg.is_leader(self.node_name):
                # we only care about Q2
                if lost_q2:
                    if self.cluster_state == healthy:
                        self.cluster_state = unhealthy
                    logger.error("i am on unhealthy state because i am the leader and i've lost some nodes in Q2")
                elif self.cluster_state == unhealthy:
                    logger.info("i switch to healty state because we have all of nodes in Q2 are alive!!!!!!")
                    self.cluster_state = healthy
                continue
            # we only care about Q1 as we are not the leader!!!
            # but if we lost Q2, then there is still no need to start a new election because we can not write any value!
            # but we can change configuration when we have Q1 alive to expel offline nodes!
            # here we do not care reconfiguration, so we need to check Q2 before we start a new election
            if lost_q1 or lost_q2:
                if self.cluster_state == healthy:
                    self.cluster_state = unhealthy
                logger.error("i am on unhealthy state because i've lost %s" % ("Q1" if lost_q1 else "Q2"))
                continue
            # we have the intersection between our Q1 and Q2 from the leader is not None
            # consequently, we can check leader state of all nodes in Q1 to decide whether we need to start a new preparation
            q1_nodes = online_nodes
            if self.quorum_strategy == "grid":
                q1_recipients = self.get_Q1_recipients()
                q1_nodes = [i for i in online_nodes if i[0] in q1_recipients]
            # below is equivalent to self.detect_partition_and_launch_prepare(online_nodes)
            # but we want to differentiate the Q1 between FPaxos and MultiPaxos
            need_elect = self.detect_partition_and_launch_prepare(q1_nodes)
            await self.start_a_new_preparation(need_elect)
        return


def run_machines():
    # test_majority()
    node_id = int(sys.argv[1])
    conf = Config(["flexible_paxos_conf.yaml"])
    machine = FPaxos(node_id, conf)
    machine.run()
    return


def main():
    # test_flexible_majority()
    # test_flexible_simple()
    # test_flexible_grid()
    run_machines()
    return

if __name__ == "__main__":
    main()

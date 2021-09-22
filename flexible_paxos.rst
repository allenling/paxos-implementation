Flexible Paxos
####################

1. https://www.sougou.io/a-more-flexible-paxos/

2. http://hh360.user.srcf.net/blog/2016/08/majority-agreement-is-not-necessary/

3. https://arxiv.org/pdf/1608.06696v1.pdf

4. https://simbo1905.wordpress.com/2016/09/29/trex-with-flexible-paxos-fpaxos-hooks/

5. https://simbo1905.wordpress.com/2016/09/30/the-fpaxos-even-nodes-optimisation/

使用
============

设置flexible_paxos_conf.yaml中的节点数量和法定人数策略, 然后启动节点

`python flexible_paxos.py 1`, `python flexible_paxos.py 2`, ....

启动客户端

`python multi_paxos_client.py`

然后在交互模式下发起命令

`choose a=1`


区分Q1和Q2
=================

这里区分出Paxos中两个阶段, 即选举阶段和写入阶段, 称为第一阶段和第二阶段

第一阶段所使用的法定人数集合为Q1, 第二节点所使用的法定人数集合为Q2, q1为Q1中的某个法定人数集合, q2为Q2中某个法定人数集合

注意q1和Q1, q1和Q2是不一样的, 比如节点数为3, N={1, 2, 3}

那么在Paxos中

Q1={{1, 2}, {1, 3}, {2, 3}}

Q2={{1, 2}, {1, 3}, {2, 3}}

我们说{1, 2}为Q1中的某个元素, 它是q1, 当然它也是q2

同时任意一个q1中的元素都属于N, q2也一样

在Paxos将Q1和Q2设置为大多数节点集合, 那么Q1和Q2是相交的, 也就是说所有的q1都相交, 所有的q2都相交, 同时任意一个q1和q2也相交

也就是所有的q(q1或者q2)都相交. 法定人数集合都相交是Paxos安全性前提条件. 这里要区分一下Q1, Q2, q1, q2


Q1和Q2所需要满足的条件
=============================

在Flexible Paxos中指出, q1之间不需要相交, 同时q2之间也不需要相交, 只需要任意一个q1都和所有的q2相交, 同时任意一个q2也和所有的q1相交, 也就是只需要要求Q1和Q2相交

**这看起来是显而易见的**

因为在Paxos中, leader掉线之后能继续保持一致性的关键在于, 新的leader能读取到之前所有写入的结果

因为任意一个q1总是和所有的q2相交, 那么无论老的leader选择哪个q2, 新的leader选择哪个q1, 新leader总是能通过重叠的节点读取到之前写入的数据, 从而保证了一致性

Paxos的大多数节点则是Flexible的一个特殊情况

**这样, 如果某个q2存活, 那么我们总是可以执行写入操作, 如果某个q1存活, 那么我们总是能执行选举操作, 两者可以不干扰**

比如我们设置Q2得节点数量为2个, Q1得节点数量为3个, 总节点数为4个, 那么只要有其他任意一个几点存活, 那么leader总是能执行写入操作

即使当前可能已经不能组成任意一个q1了

其证明基本上是 https://davecturner.github.io/2016/09/18/synod-safety.html 的详细版本, 思路是一致的, 具体请看basic_paxos.rst

Q1和Q2的取舍
=====================

文中给出了majority, simple和grid三种策略, 前2种策略基本上是Len(Q1) + Len(Q2) > N, 也就是减少哪个一个的节点数量, 另外一个的节点数量就必须增大

而grid的策略则是区别了节点到哪行哪列, 只有特定的行列上的节点掉线才会影响整个系统

很显然, 一般情况下写入比选举频繁得多得多, 如果Q2比较小, 那么写入的时候性能就更好了, 因为需要同步的节点很少

如果Q1比较小, 那么显然一旦leader掉线, 那么我们总是能选举出新的leader.

**意味着Q2越小越好?**

也不一定, Q1很小的话, 一旦leader掉线, 那么我们总是可以选举出新的leader, 然后使用reconfiguration, 把失败的节点提出集群!

**Q1比较小的优势在于能和reconfiguration结合把掉线的节点提出集群从而保证又能正常工作**, 而Q2比较小的优势在于能保证当前配置下, 可以最大限度的保证写入正常进行


增强特性(Enhancements)
========================

既然安全性的必要条件是Q1和Q2相交, 也就是新的leader必须知道之前所有的写入的值, 那么

如果我们知道前一个leader所使用的是哪个q2的话, 我们就只需要在选举的时候, 发送请求到这个q2就好了, 不必要让每个Q1和Q2都相交

换句话说, 对于proposal number=P, 我们只需要Q<P, 1>和所有小于P的Q1相交就好了. 这里我们需要记住leader所选择的q2!

当leader被选举出来之后, 需要选择一个q2, 然后广播给所有的节点, 或者存储在一个第三方服务, 或者等等. 对于一些reconfiguration, 特别有作用, 比如Vertical Paxos

这里没有实现这个增强特性

实现
=======

这里我们没有实现Enhancements中的广播Q2配置的功能, 只是简单的校验收到的ack是否满足要求而已

为multi paxos添加fpaxos特性比较简单, 我们把法定人数设置成通过函数返回, 那么每个类型的paxos重载法定人数函数就可以了

multi paxos中的Q1和Q2的条件都是N//2 + 1, 所以在multi paxos中, 我们有

.. code-block:: python

    def _set_quorums(self):
        self.half = len(self.node_names) // 2
        return

    def get_Q1_recipients(self):
        return self.node_names

    def get_Q2_recipients(self):
        return self.node_names

    def check_Q1_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.half

    def check_Q2_quorum(self, nodes: list) -> bool:
        return len(nodes) >= self.half

而对于fpaxos, check_Q1_quorum和check_Q2_quorum在majority和simple策略下, 都是判断节点个数是否满足要求而已, 而对于grid

我们需要判断是否满足当前行或当前列这个要求

.. code-block:: python

    class FlexibleGridSelector(BaseQuorumSelector):

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
            # 所有所在行的节点为Q1
            self.q1_nodes = self.row_nodes[myrow]  # all nodes in the same row
            self.q1_nodes.remove(self.node_id)
            self.q1_nodes_set = set(self.q1_nodes)
            # 所有所在列的节点为Q2
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
            # 发送resp的节点是否包含了所在行的节点
            return set(nodes).issuperset(self.q1_nodes_set)

        def check_Q2_quorum(self, nodes: list):
            # 发送resp的节点是否包含了所在列的节点
            return set(nodes).issuperset(self.q2_nodes_set)




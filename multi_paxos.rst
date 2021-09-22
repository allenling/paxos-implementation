
Multi Paxos
##################


1. Paxos Made Simple

2. The Part-Time Parliament

3. https://www.youtube.com/watch?v=JEpsBg0AO6o

4. https://simbo1905.wordpress.com/2014/10/28/transaction-log-replication-with-paxos/

5. https://simbo1905.wordpress.com/2014/10/05/in-defence-of-the-paxos-consensus-algorithm/

6. https://github.com/allenling/how-redis-cluster-works

7. https://simbo1905.wordpress.com/2016/01/02/paxos-uses-leaders-multi-paxos-is-paxos/

8. https://www.youtube.com/watch?v=YbZ3zDzDnrw

9. https://simbo1905.wordpress.com/2015/07/30/paxos-dynamic-cluster-membership-2/

10. https://simbo1905.wordpress.com/2016/12/15/paxos-reconfiguration-stalls/


使用
==========

设置multi_paxos_conf.yaml中的节点数量, 然后启动节点

`python multi_paxos.py 1`, `python multi_paxos.py 2`, `python multi_paxos.py 3`, ....

启动客户端

`python multi_paxos_client.py`

然后在交互模式下发起命令

`choose a=1`

Multi-Paxos和Basic-Paxos的关系
====================================

Basic Paxos证明了如何选择一个值, 并且这个值一旦选择就不能改变. 同时Basic Paxos允许多个Proposer一起发起写入操作, 同时并不影响正确性, 但是会出现活锁的情况

而实际使用中肯定不可能只需要决定一个值, 而是要选择多个值. 典型的使用场景就是log server.

log server把用户的每一个操作记录记录下来, 同时和其他log server同步, 然后执行这些命令. 这样即使一个log server掉线, 那么剩下的log server依然能提供服务同时具有一致性.

从Basic Paxos中延申出, 我们有这样的一个数组, 每个数组的位置称为slot, 那么每个slot就是放置用户命令

log data: [None, None, None, ....,], log data可能存储用户操作kv数据库的命令, 那么

log data: ["set a=1", "del b", "incr my_number", ..., ]

那么既然Basic Paxos能决定一个值, 那么我们就对每一个slot都执行Basic Paxos算法, 这样每个slot都是一致的, 不可更改的.

这里Paxos Made Simple中提到每个slot都由某个instance执行, 我们就看成每次选择某个slot的时候, 执行一次Basic Paxos算法

对下标为index的slot执行一次Basic Paxos算法, Prepare(pn, index), 然后Accept(pn, index, value)

而这个instance可以先直白地理解为, 每个slot我们都为其创建一个Basic Paxos对象实例, 当需要执行的时候, 调用该实例就好了. 或者把instance理解为线程也可以.

总之, instance是和slot绑定的, 要决定某个slot的时候, 就要执行该slot对应的instance

一个简单的例子

instance_map = {0: instance0, 1: instance1, ...}

要决定slot=5, 那么拿到slot=5对应的instance

instance = instance_map[5]

instance.Prepare(pn, index)

instance.Accept(pn, index, value)

显然, 在实际中不可能这么操作.


Leader
------------

虽然活锁不影响正确性, 但是活锁却影响了性能. 所以Paxos Made Simple中提出了需要一个Leader, 该Leader负责在写入数据的时候, 向其他节点同步数据(像不像Primary-Backup模式)

客户端写入的时候需要和Leader交互(其他节点可以把写入操作重定向到Leader), Leader来执行写入操作.

在参考5和7中, 分析了Multi Paxos使用Leader的论据.

既然有Leader, 那么我们就需要选举过程. 但是在Paxos Made Simple中并没有提到具体的选举过程, 只是提到了

选举可以很容易地基于timeout和随机化来实现, Paxos Made Simple重点在论证Paxos算法, 选举不是重点, 所以算是给读者的一个练习

**我们可以参考redis cluster的选举流程来实现一个简单的选举过程**


MultiPaxos的优化流程
--------------------

我们不会逐个instance执行, 这样效率太低了. Paxos Made Simple中提到, 我们只需要Leader执行一次Prepare, 这次Prepare是面向所有的slot的

其实理解起来就是所有的slot共享了Proposal Number. 当Leader执行一次Prepare, 向节点传播Proposal Number的时候

每个节点中所有的slot的Proposal Number就提升为收到的Propsal Number. 然后Leaer要向某个slot写入的时候, 直接发送Accept请求就好了.

**Multi Paxos的性能最重要的点就是一次Prepare之后, 写入只需要调用Accept就好了, 而不是每个slot都执行一次Prepare-Accept**

具体论据请看参考5和参考7


基本思路
===========

**基本原则: 不要假定网络速度, 比如假定消息在某个什么时候会收到, 有可能永远收到不, 有可能延迟, 所以唯有超时重试比较靠谱**

0. lamport中提到选举是需要基于timeout的, 同时不依赖全局时钟, 可以只依赖本地时钟

   也就是说我们总是"让出"一段时间(设置timeout), 如果在这段时间内操作成功(比如收到某些消息), 那么操作就是成功的, 否则操作失败, 需要重试.

   **redis cluster自己有一个简单可用的, 基于timeout和随机退避的方法**

1. 使用curio这个async库去处理IO.

   这个方式在使用上, 理解上比起线程更简单, 比起线程模式, 我们(几乎)不需要处理同步操作, 因为在进入await之前, 永远都是只有一个(当前)coroutine在执行

   比如当有多个客户端进行写入时, 如果使用多线程, 那么就有多个线程同时获取下一个下标, 此时必须加锁, 而如果是协程模式, 那么显然我们不必加锁

2. 简单地, 使用zfill固定消息长度, 这样我们的socket.recv就不会一次拿到多个消息了

   如果用http, 那么并没有比较简单方便的aysnc http库使用, 所以我们就简单地用socket

   所有的消息发送的时候都是字典, 然后json.dumps之后发送, 所以所有的消息抽象起来就只需要实现下面两个方法就好了

   .. code-block:: python

       class Msg(IOMsg):
           def get_dict_data(self) -> Dict:
               pass
           @classmethod
           def from_json_bytes(self, json_data:Dict):
               pass

3. 节点之间应该是一个p2p网络, 但是p2p网络有点难实现, 所以我们约定node_id大的去连接node_id小的

   比如server1只管listen, 而server2则自己listen的同时, 主动去连接server1, 然后server3同样, 自己listen的同时, 主动去连接server1和server2

4. Paxos中要求每个Proposer发起Proposal的时候, Proposal Number一定是不相交的, 也即是说来自不相交集合的(disjoint set)

   这里我们参考https://math.stackexchange.com/questions/51096/partition-of-n-into-infinite-number-of-infinite-disjoint-sets

   不相交集合的公式为S(N, n)=(2N-1)\*(2\*\*n), 比如第一个集合为S(1, n)=2\*\*n, {2, 4, 8, 16, ..., }, n>=1, 第二个集合为S(2, n)=3\*(2\*\*n), {6, 12, 24, 48, ...), n>=1

   .. code-block:: python

       def disjoint_yielder(node_id):
           odd = 2*node_id - 1
           n = 1
           while True:
               yield odd * (2**n)
               n += 1
           return

   或者使用Paxos Made Simple中的办法, Proposal Number由number.server_id, 比较的时候先比较number, 再比较server_id

   .. code-block:: python

       def disjoint_from_lamport(node_id):
           # order.node_id
           # 1.1 < 1.2 < 10.1 < 11.3 < 12.1
           # compare order first, then compare node_id
           index = 1
           while True:
               yield "%s.%s" % (index, node_id)
               index += 1
           return

5. 我们启动的时候, 会预先启动一些后台协程, 包括

   5.1 心跳协程, 这些协程定时向其他节点发送心跳

       .. code-block:: python

           async def send_node_pong(self, node_name):
               while not self._stop:
                   # 定时
                   await curio.sleep(NODE_TIMEOUT // 2 + random.randint(100, 500) / 1000)
                   # send ping
                   pong_msg = PongMsg.from_gossip_msg(self.gossip_msg, self)
                   pong_msg.set_from_node(self.node_name)
                   # 发送
                   await self.send_msg_queue.put((node_name, pong_msg))
               return

   5.2 状态检查协程, 定时取检查节点是否掉线

   5.3 发送协程, 这个协程主要是把软件中所有的IO操作都放在一个协程内发送, 这样其他协程就不需要操心发送的逻辑了, 只需要把
       目标节点地址, 以及msg对象发送到队列, 那么该协程就一直调用socket.send去发送消息

       .. code-block:: python

           async def send_node_coro(self):
               while not self._stop:
                   # 一直从队列中拿到节点名称和msg对象
                   node_name, msg = await self.send_msg_queue.get()
                   try:
                       # 拿到对应的socket
                       sock = self.gossip_msg.get_node_sock(node_name)
                       logger.debug("%s is sending msg(%s) to node %s", self.verbose_name, msg.itype, node_name)
                       if not sock:
                           logger.warning("%s have None sock for node %s, sending terminated", self.verbose_name, node_name)
                           continue
                       # 调用socket.sendall发送
                       await sock.sendall(msg.get_bytes())
                   except Exception as e:
                       logger.error("%s send node %s msg %s error", self.verbose_name, node_name, msg, exc_info=True)
                       await sock.close()
               return

   5.4 其他等等

6. 不考虑数据持久化, 也就是不会把proposal number等数据写入文件, 这里只关注算法流程


退避策略
===============

随机退避是为了让某个选举能完成, 同时也假设(希望)在退避这个时间段(timeout)内, 能完成选举同时把leader消息同步到各个节点中

下面说到心跳信息和pong消息, 其实是一个东西

否则会出现活锁, 比如A, B, C, A和B不能连接, A和B同时向C发送prepare, pn分别为1和3, C先收到了1, 然后返回ok给A, 然后再返回ok给B

.. code-block::

   A(0)  X  B(0)        A(1)  X   B(0)          A(1) X  B(3)        A(5)  X B(3)

                ====>                    ===>                 ===>
   C(0)                 C(1)                    C(3)                C(5)

那么A和B都发现自己是leader, 结果就是A发送的accept被C拒绝, 然后再次发送prepare给C, 打断B的accept, 重复下去A和B都无法进行accept

随机退避
-------------------------------

**首先, 节点只有收到其他节点的心跳才会把对方标识为在线状态的**

一开始A, B, C三者收到了各自的第一个心跳, 发现都没有leader, 那么A, B, C先随机休眠一段时间

然后B先苏醒, 然后发起prepare给A和C, 在A醒来之前, B成为了leader, 其pn为3

此时A苏醒, 为了不让A去打断B, 我们需要在心跳带上leader信息, A通过B和C的pong消息发现B是leader, 那么A就不会去发送prepare了

**休眠时间太长则会延迟选举, 太短的话, 还是无法避免活.** 比如

A在t1时间醒来发送prepare, 其pn=1, B在t2时间醒来然后发送prepare, 其pn=3

在t1-t2之间, 可能A没有选举成功, 比如可能是B发送的prepare ack延迟了, 可能A选举成功了, B没有感知到, 比如A的pong消息没有发送到B

.. code-block::

         A          B

    t1   1 ----->

    t2     <-----   3

    t3   5 ----->

A由于没有感知到B是leader(心跳信息延迟了), 那么在t3又再次醒来发送prepare

prepare消息的次数限制和心跳同步
-------------------------------------

所以这里我们加入一个限制, 在一定时间内, 比如NODE_TIMEOUT=10s, 一个节点只能回应一次prepare消息, 同时如果自己已经回复过一次prepare消息了, 在NODE_TIMEOUT内, 不会发起prepare

**所以这里让出了一段时间(timeout), 让已经开始的流程能顺利完成.**

1. A的prepare在t1时间到达B, B在t2时间醒来, 发现已经接收到了一个prepare了, 那么继续休眠, 等待A选举成为leader

2. B的prepare在t1时间到达A, A在t2时间醒了, 发现已经接收到了一个prepare了, 那么继续休眠, 等待B选举成为leader

3. A和B醒来发现没有回复过任何prepare请求, 那么A和B同时开始向对方发送prepare, 那么B的pn大于A的, 所以B不会回复A, 而A发现收到的prepare大于自己的pn, 那么回复ok给B

这样我们就希望在NODE_TIMEOUT时间内有且只有一次选举进行, 这样选举大概率能完成

注意的是, **我们收到prepare之后会阻止发送prepare操作, 但是发送prepare却不会阻止接收prepare.**

如果A, B均在发送prepare之后总是忽略任何prepare请求, 那么A和B都无法完成选举了, 比如

在上面情况3下, A收到B的prepare请求, 发现自己已经发送过一次prepare了, 那么拒绝, 然后B也发现自己已经发送了一次prepare, 同样也拒绝A的prepare, 那么此次无人成功

.. code-block::

    A         B

    1         3

       1----->X

    X<------3


如果我们考虑我们还有一个节点C, 那么的情况是

1. A, B, C通过第一个pong消息, 发现各自都没有leader, 那么休眠然后A和B互相发送prepare, 然后B会成为leader, 此时C通过pong消息发现leader是B, 那么C通过pong消息同步leader

2. C在A和B选举成功之前休眠醒了, 此时C收到的第一个pong消息发现没有leader, 然后C发起prepare

   如果B已经收到了A的prepare, 那么此时是在NODE_TIMEOUT时间内, 那么B拒绝掉C, B成为leader

   .. code-block::

             A         B           C

       t1    1         3

       t2        1--->

       t3              X <-------  5


3. 如果B没有收到A的prepare, 由于C的pn大于B的pn, 那么C会取消掉B的prepare流程, 这样B会回复prepare ack给C, C会成为leader

   .. code-block::

             A         B           C

       t1    1         3

       t2              5 <-------  5

       t3      1------>X

4. 而对于A, 无论谁的prepare先到达, 并不影响leader选举, 因为在NODE_TIMEOUT内, A只会回复prepare ack给其中一个节点

允许抢夺leader
-----------------

如果在NODE_TIMEOUT内没有同步leader(比如pong消息延迟了), 那么leader节点显然要么掉线了, 要么网络不好, 这就需要节点们再次启动prepare流程了, 比如

B收到A和C的prepare ack, 没来得急发送pong就掉线, 或者pong延迟到达A和C, 那么此时A和C经过NODE_TIMEOUT之后发现依然没有leader, 那么允许A和C重新发送prepare

.. code-block::

    A(10, None)  X  B(10, B)        A(10, None)    B(X)           A(15, A)  B(X)

                            ===>                            ===>
    C(10, None)                     C(10, None)                   C(15, A)

或者C在某些情况下, 有可能抢夺掉B的leader权限, 比如

A和B选举, B是leader, C收到A和B的第一个pong消息, 发现都没有leader, 然后休眠

经过很久, 至少NODE_TIMEOUT, 之后, C还收不到A和B的pong消息, 那么此时C向A和B

发起prepare, 由于C的pn是最大的, 那么C将会抢夺掉B的leader权限.

**我们是否能说, 如果A和B之间保持稳定状态, 也就是A和B都同步leader是B, 并且A和B网络通畅的情况下 拒绝掉C的prepare?**

不能, 因为如果A和B拒绝掉C的prepare, 那么由于A和B的pn都小于C, 那么C会无视所有小于自己pn的pong的, 所以C既不能抢夺leader权限, 也不能通过pong升级leader, 那么C就永远加入不到集群中了.

更大的prepare抢占leader权限这是无法避免的, 因为我们依赖于心跳的, 无法假设网络情况, 是否有延迟等等情况


选举时机和网络分区
======================

关于网络分区, 我们简单分为两种情况

1. 分区之间是完全隔离的, 比如{1, 2}, {3}, {4, 5}, 或者{1, 2}, {3, 4, 5}

   此时处于大多数集合的节点们, 比如{3, 4, 5}, 发现所有的节点都和leader失去连接了, 那么显然此时要发起选举了


2. 分区之间并不是完全隔离的, 比如

   {1, 2}, {2, 3, 4}, {5}

   {1, 3}, {3, 4, 5}, {2}

   {1, 2}, {2, 3}, {3, 4}, {4, 5}

对于2的情况, leader依然能正常工作的话, 我们是不需要选举的, 比如1是leader

   {1, 2, 3}, {3, 4, 5}

   {1, 3} {1, 2}, {3, 4, 5}, 这里即使2, 3不相连接, 但是1还是能正常工作

   对于{3, 4, 5}中4, 5发现3还能和1相连, 那么应该不需要发起选举

   但是如果是这样{1, 3}, {3, 4, 5}, {2}

   3依然能和leader相连, 但是{1, 3}并不能正常工作, 所以此时应该去选举, 不然整个集群都工作不了

当一个节点处于大多数集合(majority set), 并且至少有一半的节点的pn和我们一样, 同时leader在线, 那么该节点的cluster_state就是healthy的, 否则就是unhealthy的

.. code-block:: python

    half = len(self.node_names) // 2
    same_pn_online_nodes = [i for i in online_nodes if i[1]["prepare_pn"] != -1 and i[1]["prepare_pn"] == self.prepare_pn]
    if len(online_nodes) < half:
        if self.cluster_state == ClusterState.healthy:
            # we are in a minority set, so set unhealthy state
            self.cluster_state = ClusterState.unhealthy
        # if we are not in a majority set, then we can't do anything
        continue

    if len(same_pn_online_nodes) < half:
        if self.cluster_state == ClusterState.healthy:
            logger.info(f"{self.verbose_name} in a minority pn({self.prepare_pn}) set of majority set")
            self.cluster_state = ClusterState.unhealthy
    elif self.gossip_msg.is_leader_offline():
        if self.cluster_state == ClusterState.healthy:
            logger.info(f"{self.verbose_name} lost leader")
            self.cluster_state = ClusterState.unhealthy
    elif self.cluster_state == ClusterState.unhealthy:
        logger.info(f"{self.verbose_name} switch to healthy state!!!!")
        self.cluster_state = ClusterState.healthy

判断是否需要发起prepare的时候, 校验leader的cluster_state

.. code-block:: python

    any_others_see_leader = [i for i in online_nodes if i[1]["leader_online"]]
    need_elect = False
    # we are in a majority set
    if not any_others_see_leader and self.gossip_msg.is_leader_offline():
        # all of other nodes can't connect to leader, and i can't see the leader neither, then start a new election!
        # {1, 2}, {3, 4, 5}
        need_elect = True
    elif any_others_see_leader and self.gossip_msg.is_leader_offline():
        # {1, 3}, {2}, {3, 4, 5}, we are 4, and we know 3 can see leader
        online_node_leader_cluster_state = [self.gossip_msg.get_node_leader_cluster_state(i[0]) for i in
                                            any_others_see_leader]
        need_elect = True
        # 3 says that the leader is on healthy state, then we don't start a new election
        # otherwise, feel free to start a new election!
        if any([i == multi_paxos_msg.ClusterState.healthy.name for i in online_node_leader_cluster_state]):
            # check there is any node can see leader is on healthy state
            # because 5 can't connect to leader, so the leaders cluster state may be stale
            need_elect = False
    elif not any_others_see_leader and self.gossip_msg.is_leader_online():
        # {1, 3}, {2}, {3, 4, 5}, we are 3, and we know 4 and 5 can't see leader
        # and we can see leader, we need to check leader's cluster_state
        leader_cluster_state = self.gossip_msg.get_leader_cluster_state()
        if leader_cluster_state == multi_paxos_msg.ClusterState.unhealthy.name:
            need_elect = True

比如{1, 3}, {2}, {3, 4, 5}中, leader为1

1看到自己处于minority集合中(1只和少于一半的节点互连), 那么更新自己的cluster_state为unhealthy, 同时因为自己的leader, 那么leader_cluster_state就等于自己的cluster_state

1.pong.leader_cluster_state = unhealthy
1.pong.leader_online = True

而3接收到1的pong之后, 发现4和5都看不到1, 同时检查看到1的cluster_state为False, 那么3可以发起选举, 3把自己的leader_cluster_state设置为unhealthy, 因为3看到leader的其自己的cluster_state为unhealthy

3.pong.leader_cluster_state = 1.pong.leader_cluster_state
3.pong.leader_online = True

那么对于4, 发现3还可以看到leader, 但是4通过3知道1已经处于unhealthy状态了, 所以4也可以发起选举. 4不会去查看5的leader_cluster_state字段的, 因为5并没有和1相连.


而对于 *len(same_pn_online_nodes) < self.half* 这个情况, 在下面给出

pong(gossip)消息同步
=======================


pong消息带有下面这些数据

.. code-block:: python

    {"leader": None, "leader_online": False, "prepare_pn": -1, "leader_cluster_state": None}


初始情况
-------------

1. 一开始只有A和B两个节点, A和B互相发送prepare给对方, 两者的状态都是

   .. code-block::

       A       B

   leader=None, prepare_pn=-1, leader_online=False, leader_cluster_state=None

2. 当leader被选举出来之后, 假设B为leader, 那么B的pong消息就是

   leader=B, prepare_pn=10, leader_online=True, leader_cluster_state=True

3. 当A收到B的pong消息, 发现pong中的pn和我们的相等, 同时A的leader为None, 那么显然需要同步leader为B, 所以A的状态就同步为

   leader=B, prepare_pn=10, leader_online=True, leader_cluster_state=True

   .. code-block::

       A(10, B)       B(10, B)

C通过pong同步leader为B
--------------------------

如果C和A, B通信顺畅, C通过A或者B的pong消息发现的它们的pn大于自己的pn(初始的时候, C.pn=-1), 同时发现leader是B, 那么C的leader也被同步为B

.. code-block::

    A(10, B)       B(10, B)


    C(10, B)

C抢夺leader
-------------------

1. C收到A或者B的第一pong消息之后, 确认自己在大多数集合中, 之后A和B都选举完成, B为leader, 然后C就没有收到任何pong(可能因为延迟)

   那么C开始抢夺leader权限, 发送prepare, 其pn=15

   **假设C和B无法连接, 那么A收到C的prepare之后**, 提升自己的pn为15, 设置自己的leader为None, 此时B的所有请求都会被拒绝

   .. code-block::

       A(10, B)     B(10, B)   A收到C.prepare之后            A(15, None)    B(10, B)
                              =====================>

       C(15, None)                                          C(15, None)

   如果顺利, C将会变为新的leader, A通过C的pong消息就发现C是leader, 那么同步leader, B也通过A的pong消息发现A的pn比自己的大, 同时存储又leader信息, 那么B升级leader为C

   此时C的gossip消息为: leader=C, prepare_pn=15, leader_online=True, leader_cluster_state=True

   .. code-block::

       A(15, C)       B(10, B)             A(15, C)        B(15, C)
                                   ====>

       C(15, C)                            C(15, C)

**这里有个问题, 如果C的prepare请求晚于pong消息到达A呢?** 此时A通过C.pong发现C的pn=15大于自己, 但是leader为None. 如果我们直接把A的pn升级为15, 那这样proposal number就有两个地方可以修改了

分别是prepare和pong, 这样不好. 因为根据paxos, proposal number必须是只有prepare能修改.

所以这里A什么都不做, A判断如果C的pong消息的pn大于自己但是没有指定leader, 那么表示我们在等待prepare.

.. code-block::

    C的prepare到达之前, C提升自己的pn=15, 然后C.pong.pn=15, 当C.pong到达A的时候, A上面都不做
    A(10, B)     B(10, B)


    C(15, None)

.. code-block:: python

    if msg_obj.prepare_pn > self.prepare_pn:
        if msg_obj.leader:
            # 升级leader
            self.prepare_pn = msg_obj.prepare_pn
            self.log_data_manager.reset_batch_accept_chosen()
            self.gossip_msg.set_leader(msg_obj.leader)
        # 否则什么都不做, 等待prepare
        return

此时B依然可以处理写入操作. 当C的prepare到达A之后, A的pn才被提升为15, 此时A会重置leader为None, 否则B从A的pong消息中看到pn=15, leader=B, 这是很混乱的

.. code-block:: python

    if msg_obj.prepare_pn < self.prepare_pn:
        # pn小于等于自己, 无视
        pass
    else:
        self.prepare_pn = msg_obj.prepare_pn
        # 重置leader
        self.gossip_msg.set_leader(None)

之后C得到A的回复之后, 把leader设置为自己, 此时A通过C的pong消息发现leader是C, 那么更新自己的leader, 同时B通过A的pong消息发现pn=15大于自己同时leader为C, 那么

B升级自己的leader为C(上面代码块中升级leader那部分)

假设这样一个例子, 有网络分区{1, 2}, {3, 4, 5}, 1是leader

显然{3, 4, 5}会选举除新的leader, 假设为4, 然后此时2和4的连接建立了, 那么此时2收到4的pong之前, 收到了4的accept(pong延迟)

那么此时2将会丢弃这次accept, 因为2此时的leader仍然是1, 节点不会接收非leader的accept, 直到2收到4的pong之后才会升级leader, 但这不会影响

4的整体的accept过程. 这个流程和paxos中的不太一样, 按照paxos的流程, 此时2是直接接收4的accept的, 但是因为阻碍4的accept流程, 所以这里也无所谓

C未发送prepare然后掉线
--------------------------

如果C没有发送prepare就掉线, 那么对A和B没有影响, 因为A只有收到C的prepare之后才会提升pn


C在发送pong之前掉线
-------------------------------

A收到C的prepare之后, C在收到A的ack之前就掉线, 或者C收到了A的ack, 但是没有发送pong消息就掉线了, 或者C的pong消息延迟很久才会到达A

那么此时A和B的状态就是

.. code-block::

    A(15, None)    B(10, B)
                      X
                    C(X)

此时我们需要A和B能够恢复正常, 因为A和B不知道C怎么了, 所以只能通过timeout来判断, 如果处于错误状态太久, 那么强行回正

1. B发现集群处于unhealthy状态, 因为B虽然能和大多数节点相连, 但是具有相同pn的节点少于一半, 此时pn=10的节点除了B就没了, 所以0<1, 所以B可能立马发起prepare

2. A经过NODE_TIMEOUT之后, 发现自己能和大多数节点相连, 但是leader为None, 所以A会发起prepare

如果B立马发起prepare, 但是因为A在NODE_TIMEOUT内已经接收了C的prepare, 那么A将会拒绝B的prepare, 然后B就会再等待一段时间

而A也可能此时会发起prepare, 但是A自己发现NODE_TIMEOUT内, 自己已经接收了C的prepare, 那么A也会等待一段时间再发起prepare, 所以

不正常的状态最多持续NODE_TIMEOUT时间

如果在NODE_TIMEOUT时间内:

1. C的pong消息达到A, 那么A和B都能通过pong同步leader为C

2. C的pong消息经过很久依然没有到达A, 可能C已经掉线了, 此时已经过了NODE_TIMEOUT了, 那么A和B总会有一个能选举成功的


C同步完leader之后掉线
---------------------------

A和B通过C的pong消息同步完leader为C之后, C掉线了, 那么此时A和B就发现没有人能发现C, 那么A和B就会再次发起选举


leader掉线后又重启
---------------------

节点A和B, A是leader, 然后A和B的无法收到各自的pong消息(比如超时)

1. 如果A并没有重启, 只是网络抖动, 当A和B之间网络恢复之后, 系统正常运行

2. A重启了, 因为这里我们并没有实现持久化, 所以如果B继续把A当作leader的话

   A的data就是脏数据所以我们这里简单的把所有replica的leader都移除, 这样大家可以重新启动新的一轮选举

   .. code-block:: python

        # B发现A的pn小于自己
        if msg_obj.prepare_pn < self.prepare_pn:
            # A重启之后, A的pn就是-1, 小于B.pn, 同时B发现A的自己的leader, 移除B的leader
            if msg_obj.from_node == self.gossip_msg.get_leader():
                logger.info("we get the old leader, remove the leader nomination")
                self.gossip_msg.set_leader(None)
            return

        # A发现B的pn大于自己
        if msg_obj.prepare_pn > self.prepare_pn:
            if msg_obj.leader:
                # A发现B的leader是自己同时自己的pn是-1, 说明我们重启了, 等待B移除leader提名
                if msg_obj.leader == self.node_name and self.prepare_pn == -1:
                    # we were the leader but now restart, consequently, we need to start a new preparation later!
                    return


如何判断节点是否掉线?
=======================

1. 我们和某个节点之间的连接断开了, 比如socket.recv报错, 那么此时说明掉线了, 直接把节点标识为offline

2. 如果对方的socket没有释放, 那么recv可能不会报错(?), 所以我们约定如果超过一定时间没有收到某个节点pong消息, 那么我们就说该节点掉线了

.. code-block:: python

    if time.time() - last_pong_time >= NODE_TIMEOUT:
        nodes[node_id] = OFFLINE

这里我们参考redis cluster, 约定了一个集群的timeout时间NODE_TIME作为判断基准, 目的是防止网络抖动, 随意设置的

如果节点掉线又在线, 那么我们可以通过pong消息更新状态, 并且我们建立连接不能说明对方存活, 只有收到pong消息之后才会确定该node是online状态

.. code-block:: python

    async def handle_pong(self, msg_obj: PongMsg):
        """
        update gossip
        """
        # TODO: save prepare proposal number into file
        from_node = msg_obj.from_node
        self.gossip_msg.update_node_last_pong_time(from_node)
        # set online
        self.gossip_msg.set_node_online(from_node, msg_obj.get_data())

如果我们通过其他节点发现其他节点和Leader依然相连, 我们可以利用这个级联关系, 让其他节点转发accept给我们而不需要发起Prepare

.. code-block:: python

    self.gossip_msg.is_leader(msg_obj.leader) and msg_obj.timestamp - time.time() >= NODE_TIMEOUT:
        logger.info("%s found out that the leader is still alive through node %s, but we don't do anything for now",
                    self.verbose_name, msg_obj.from_node,
                    )
        # TODO: issue a transmission

现在并没有使用上这个级联关系, 所以没有实现


Takeover协议
===============

通过选举过程, 我们可以说我们总是只有一个leader在线了

根据Paxos协议, 新的Leader必须先同步所有数据才能进行accept操作, 所谓的takeover协议, 不然会出现数据冲突

根据https://cse.buffalo.edu/tech-reports/2016-02.orig.pdf, 提到ZAB和Raft在新leader同步数据上的区别

1. ZAB会有在选举成功之后, 那么需要有一个同步阶段去同步数据, 需要向大多数节点广播同步好的数据之后(大多数节点响应), 才能开始写入

2. Raft会在每次写入一个数据之后, replica会发送自己的数据index回给Leader, 然后Leader会再发送需要同步的数据给replcia

   所以Raft把所有的同步操作都放在心跳中

半同步数据
--------------

**这里我们结合两者的方法, 半同步数据**, 同时也是为了让Prepare过程更清楚, 这里我们引入Prepare Sync阶段

我们在Prepare Sync阶段只同步Leader自己的数据, 但是不广播给所有的节点, 而是更新我们的数据下标, 我们在pong消息中通过比对数据下标的方式发送同步数据

**比起ZAB, 我们没有在leader同步完数据后, 发送给节点然后等待节点响应, 所以省了一次发送-响应过程, 比起Raft, 我们在prepare阶段进行同步leader数据更简单一点**

因为在pong消息中同步的话, leader要和每个节点都比较一次all_chosen_index, 这里统一比较更简单

首先对于log data, 我们保存当前写入的最大下标log_index, 以及所有小于某个下标的slot都是chosen状态, 称这个下标为all_chosen_index

.. code-block::

    log_data: [(value=a, chosen), (value=b, chosen), ..., (value=k, chosen), (value=p, Accepted), (value=None, Empty)]

从a-k, 所有的slot都chosen状态, 那么假设k的下标是7, 那么all_chosen_index=7, 同时slot8中的值p处于没有chosen, 而slot9是一个空的slot

.. code-block::

    log_data: [(..., (pos=7, value=v7, chosen), (pos=8, value=v8, Accepted), (pos=9, value=None, Empty), ...]

所以log_index=9. log_index和all_chosen_index不一样是因为Paxos可以并发地写入, 也就是说slot9不可以不等待slot8变为chosen状态就写入

我们在pong中比对的就是all_chosen_index

Prepare Sync流程
-------------------

1. 发送Prepare, 得到至少大多数节点返回, 那么我们可以说我们是Leader了

   .. code-block:: python

       async def prepare(self):
           # 组装prepare消息
           prepare_msg = multi_paxos_msg.PrepareMsg(self.prepare_pn)
           prepare_msg.set_from_node(self.node_name)
           self.prepare_ack_evt = AckEvt(self.prepare_pn, multi_paxos_msg.MsgType.PREPARE_ACK)
           # 发送给所有的节点
           for node_name in self.quorum_selector_instance.get_Q1_recipients():
               await self.send_msg_queue.put((node_name, prepare_msg))
           # wait for majority
           # 在这个event上等待返回
           await self.prepare_ack_evt.wait()
           if self.prepare_ack_evt.is_suc():
               # prepare成功, 继续下一步
               pass
           else:
               # 等待下一轮prepare
               pass

   收到prepare之后发送prepare ack, 我们收到prepare ack之后, 减少self.prepre_ack_evt的计数, 直到计数为0或者超时

2. 发送Prepare Sync消息, 让所有节点返回min_index和max_index之间的数据, 然后Leader取choose每一个slot, 最终[a2, b3]之间的数据都是chosen的

   prepare成功的话, 我们知道每一个节点的数据的左右边界, 所有下标小于左边界的数据都是chosen的, 有边界是数据最大下标

   左边界称为all_chosen_index, 右边界为log_index

   如下面所示, 显然我们需要同步的数据就是[a2, b3]这个区间, 所以我们需要节点返回[a2, b3]的数据, 左边界我们称为min_index, 右边界我们称为max_index

   .. code-block::

       all_chosen_index=a, log_index=b
       node1: ---------------a1------------b1----------
       node2: --------a2----------b2-------------------
       node1: ------------a3----------------------b3---

   所以我们需要发送prepare sync消息, 每个节点都返回自己的左右边界, leader根据每个节点的边界, 确定一个最终的数据长度, 就是上面的[a2, b3]

   这个区间内所有的数据都是chosen. leader同步好自己的数据之后, 不会发送额外的请求把这些数据同步给节点, 而是通过定时任务去同步的

3. 在pong消息中判断节点的all_chosen_index和Leader自己的all_chosen_index, 如果节点的all_chosen_index比较小, 显然我们需要发送同步数据

   那么我们就把需要同步的数据记录下来, 定时去同步

   如果我们当前all_chosen_index是10, 而对方的all_chosen_index是5的话, 那么下面get_batch_chosen_list函数就是返回[6, 10]之间的数据

   .. code-block:: python

       new_batch_chosen_index_list = self.log_data_manager.get_batch_chosen_list(from_node, msg_obj.all_chosen_index)
       for i in new_batch_chosen_index_list:
           if i not in self.chosen_broadcast_list[from_node]:
               data = self.log_data_manager.get_data(i)
               # 加入到定时发送列表中
               self.chosen_broadcast_list[from_node][i] = [data.pos, data.value, data.req_id]


具体同步的过程在后面

Learner和Accept
==================


通过选举和takeover过程, 我们能保证稳定情况下只有一个leader负责写入操作. Leader的写入其实就是发送Accept请求而已

只要写入某个值的时候, 收到至少大多数的节点返回, 那么这个某个值就确定了(chosen状态)

对于client来说, 要写入一个值就是向Leader发送一个choose请求, 而Leader选择下一个log data slot, 发送Accept请求, 一旦收到大多数节点返回成功

那么向客户端返回成功, 否则返回超时

这里如果实现了论文中的a值限制的话, 那么下标为i的数据必须等待i-a的下标已经是chosen状态才可以执行accept

所以下面的while循环就是处理a值限制的


.. code-block:: python

    async def handle_choose(self, choose_cmd: ClientChooseCmd):

        while True:
            log_index = self.log_data_manager.get_next_log_index()
            if log_index is not None:
                break
            await curio.sleep(0.01)
        # 组装accept消息
        accept_msg = multi_paxos_msg.AcceptMsg()
        accept_msg.set_from_node(self.node_name)
        accept_msg.set_prepare_pn(self.prepare_pn)
        accept_msg.set_pos_and_value(log_index, value)
        accept_msg.set_req_id(req_id)
        accept_ack_evt = AckEvt(self.prepare_pn, resp_type=multi_paxos_msg.MsgType.ACCEPT_ACK)
        self.accept_ack_evts[log_index] = accept_ack_evt
        # 发送给所有的节点
        for node_name in self.quorum_selector_instance.get_Q2_recipients():
            await self.send_msg_queue.put((node_name, accept_msg))
        # wait for majority
        await accept_ack_evt.wait()
        # Event返回之后, 判断状态
        if not accept_ack_evt.is_suc():
            # 这里向客户端返回写入超时了
        else:
            # 返回成功给客户端

在Paxos中还有个角色叫Learner, 目前并没有讨论. 先考虑一下这个情况, 节点1, 2, 3, 1是leader

1. client C1发送命令incr key=a

2. leader 1 发送accept(pn=10, index=15, value="incr key=a")给所有的节点, 此时节点2, 3收到accept, 发送accept_ack

3. 网络原因, L1没有收到2, 3的accept_ack, 然后通知C1此次写入失败(超时)

4. L1掉线, N2被选举为新的leader L2, 然后L2发现index=15中已经accpet了"incr key=a", 那么选择这个incr命令作为index=15的最终值

5. 然后L2, 和3都执行该命令, 此时a从21变为了22

6. C1再次发送写入操作, 然后a就被incr了2次

**也就是说基于超时的话, 我们不能判断其他节点到底是掉线了呢? 还是返回延迟?**

Client在写入之前需要直到这条命令是否已经被写入了, 或者说Leader在发起写入操作的时候, 需要直到这条命令是否被写入了, 我们需要Learner这样的角色!

**其实在Paxos的论文中, 一个值是否被chosen是通过Learner来决定的, Acceptor把accept了哪个值发送到Learner**

Learner通过这些信息判断是否某个值被大多数Acceptor给接受了, 然后记录下chosen的值

只是之前我们把Proposer和Learner的角色合并了, Acceptor把accept的结果返回给Proposer, 所以Proposer直到哪些值被chosen了

这里我们依然把Proposer和Learner合并起来, 或者说把Proposer, Acceptor, Learner三者都实现在同一个实例中

choose完成之后, 我们Leader还充当Learner的角色, 把chosen的值广播给其他所有的节点

根据参考视频3中提到的方法, 在Client发送choose请求给Leader之前, 生成一个request_id, 发送给Leader, 然后每次Leader会记录下request_id是否成功

Leader写入之前查询该request_id是否成功, 或者Client在写入失败之后, 重试之前查询是否成功再决定是否发起choose请求.

**所以我们必须后台一直重发这些超时的accept请求, 同时还要支持查询写入请求状态**

后台发送Accept
------------------

这里我们可以合并超时的Accept请求, 不然我们的accept请求有点多啊, 比如我们当前有100个超时的accept, 那岂不是有100个accept请求.

所以我们这里把所有超时的acecpt请求都存到一个列表中, 然后定时去批量发送accept. 这里我们在启动一个后台定时任务, 定时去发送超时的acecpt


.. code-block:: python

    async def handle_choose(self, choose_cmd: ClientChooseCmd):

        # Event返回之后, 判断状态
        if not accept_ack_evt.is_suc():
            # 记录下哪些slot需要重新发送accept!!!!!!
            self.accept_ack_evts[log_index] = AckEvt(self.prepare_pn, resp_type=multi_paxos_msg.MsgType.BATCH_ACCPET_ACK)
            # 重发的accept列表
            self.retry_accept_data[log_index] = [log_index, value, req_id]
            # 记录下request_id对应的状态
            self.req_id_history[req_id] = ReqidInfo(log_index, req_id, multi_paxos_msg.LearnState.timeout)
            # 把自己的slot设置为accepted状态, 因为我们自己也是一个replica
            self.log_data_manager.mark_slot_accepted(self.prepare_pn, log_index, value, req_id)
            # 这里向客户端返回写入超时了
        else:
            # 返回成功给客户端


    # 定时任务发送accept
    async def background_batch_accept(self):
        while not self._stop:
            # 每次休息NODE_TIMEOUT的时间
            await curio.sleep(multi_paxos_msg.NODE_TIMEOUT + random.randint(1000, 2000) / 1000)
            if not self.gossip_msg.is_leader(self.node_name):
                continue
            logger.debug("background_batch_accept %s", self.retry_accept_data)
            if not self.retry_accept_data:
                continue
            msg = multi_paxos_msg.BatchAcceptMsg()
            msg.set_data(list(self.retry_accept_data.values()))
            msg.set_prepare_pn(self.prepare_pn)
            msg.set_from_node(self.node_name)
            # 发送给所有的节点
            for node_name in self.quorum_selector_instance.get_Q2_recipients():
                await self.send_msg_queue.put((node_name, msg))
        return

    # replica收到batch accept请求之后, 把这些slot都设置为accepted
    async def handle_batch_accept(self, msg: multi_paxos_msg.BatchAcceptMsg):
        pos_list = []
        for pos, value, req_id in msg.data:
            pos_list.append(pos)
            # 设置为accepted状态
            self.log_data_manager.mark_slot_accepted(msg.prepare_pn, pos, value, req_id)
        resp = multi_paxos_msg.BatchAcceptAckMsg()
        resp.set_from_node(self.node_name)
        resp.set_prepare_pn(self.prepare_pn)
        resp.set_pos_list(pos_list)
        await self.send_msg_queue.put((from_who, resp))
        return

    # 如果收到batch accept的返回之后, 计算是否有半数的几点返回成功, 如果是, 那么把某个index设置为chosen
    async def handle_batch_accept_ack(self, msg: multi_paxos_msg.BatchAcceptAckMsg):
        for pos in msg.pos_list:
            if pos not in self.accept_ack_evts:  # chosen
                continue
            # self.accept_ack_evts[pos].get_ack_sync这个函数会判断是否有半数的节点accept了
            # pos下标对应的slot, 所以是, 那么ret就是True, 表示pos这个slot应该是chosen了
            # 把数据同步给定时同步chosen的任务
            ret = self.accept_ack_evts[pos].get_ack_sync(msg, self.quorum_selector_instance.check_Q2_quorum)
            if ret:
                log_data = self.log_data_manager.log_data[pos]
                del self.retry_accept_data[pos]
                del self.accept_ack_evts[pos]
                # mark_clot_chosen会处理all_chosen_index的
                self.log_data_manager.mark_slot_chosen(self.prepare_pn, pos, log_data.value, log_data.req_id)
                # 需要定时同步给所有的节点这个slot是chosen状态
                for name in self.node_names:
                    self.chosen_broadcast_list[name][pos] = [pos, log_data.value, log_data.req_id]
        return

Client和Learner
===================

我们这里启动后台定时任务, 定时把chosen的值广播到其他节点. 这里会出现这样的情况

我们广播3, 4, 5这3个chosen的slot给N2, N3, N2返回成功, 那么下一次广播给N2的时候就去掉3, 4, 5这3个slot

然后接着6, 7, 8这3个slot变为chosen了, 那么把slot6, 7, 8发送给N2, 而N3对于slot3, 4, 5没有返回

那么下次就把slot6, 7, 8合并一起, 把slot3, 4, 5, 6, 7, 8发送给N3, 也就是合并发送

处理过程和同时发送accept差不多

.. code-block:: python

    # 后台定时发送batch chosen
    async def background_batch_chosen(self):
        while not self._stop:
            st = multi_paxos_msg.NODE_TIMEOUT + random.randint(1000, 2000) / 1000
            await curio.sleep(st)
            if not self.gossip_msg.is_leader(self.node_name):
                continue
            logger.debug("background_batch_chosen %s", self.chosen_broadcast_list)
            # 哪个节点需要同步哪些数据
            for node_name, pos_datas in self.chosen_broadcast_list.items():
                if not pos_datas:
                    continue
                datas = list(pos_datas.values())
                msg = multi_paxos_msg.BatchChosenMsg()
                msg.set_from_node(self.node_name)
                msg.set_prepare_pn(self.prepare_pn)
                msg.set_data(datas)
                await self.send_msg_queue.put((node_name, msg))
        return


reconfiguration(Horizontal Paoxs)
===========================================

这里并没有实现reconfiguration, 因为这里的reconfiguration问题比较多, 详见SMART协议

slot的并行
--------------------

Paxos中假定每一个slot之间是独立的, 所以每个slot可以不等待其他slot的命令变为chosen之后才开始写入, 而是并发地写入, 比如下面3个命令

(10, a=1), (11, b=2), (12, a=a-1)

在10这个slot没有chosen的时候, 12这个slot可以发起写入, 称为pipeline

这样也不会有危险, 因为这里我们执行命令是和all_chosen_index有关的, 也就是执行命令的时候只按照all_chosen_index的顺序来执行

.. code-block::

    all_chosen_index
        (9, c=3)          (10, a=1)  (11, b=2)  (12, a=a-1)  (13, c=c-1)  (14, b=b+1)
         chosen                       chosen       chosen                    chosen

这里即使12是chosen状态, 由于我们总是只按照all_chose_index来顺序执行命令, 所以目前也不会执行12这条命令, 因为all_chosen_index为9, 所以a的值没有变化

当10变为chosen之后, 那么all_chosen_index往前增长变为12, 然后那么执行10, 11, 12这个3条命令

然后继续等待13这个命令变为chosen, 之后再执行13, 14这两条命令

但是注意的是, 这里涉及到返回结果给客户端, 所以如果12这条命令是chosen了, 那么我们应该告诉客户端这条命令已经写入了, 但是可能没有立即生效

甚至, 在参考9和参考10中提到, 对于一个key系统, 不同的key是可以并行处理的, 只有针对同一个key的操作才必须严格有序, 对于上面的例子

10和12是必须先执行10再执行12的, 但是对于11, 我们可以同时执行10和11, 而12要等待10执行完成之后才能执行

关于pipeline

https://www.zhihu.com/question/267436664/answer/524574389
顾名思义，流水线。比如你要组装一个 iPhone 手机，其中分为五个步骤，每个步骤需要使用不同的设备。有两种组装方式。假设每个步骤需要的时间为 1。
1. 组装完了一个设备之后再组装另一台。组装 5 台的时间为 25.
2. 当第一台手机完成第一个步骤后，第二台手机开始第一部分的组装。总时间为 9。使资源得到重复利用。

https://en.wikipedia.org/wiki/Instruction_pipelining
In computer science, instruction pipelining is a technique for implementing instruction-level parallelism within a single processor.
Pipelining attempts to keep every part of the processor busy with some instruction by dividing incoming instructions into a series of
sequential steps (the eponymous "pipeline") performed by different processor units with different parts of instructions processed in parallel.

alpha的限制
----------------------

Paxos中reconfiguration的方法是使用算法本身来修改节点集合, 也就是把reconfiguration写入到某个slot中

这样的话后续的slot就必须知道正确的, 修改过之后的节点集合是什么, 那么一旦发起reconfiguration, 那么我们就必须等待这个命令chosen之后, 才能执行后续的写入操作

所以reconfiguration会使得并发性降到1, 而lamport引入了alpha的限制, 限制reconfiguration从写入到生效的距离, 也即是说

假设有位置i, 从1, ..., i的slot都是chosen的(称为all_chosen_index), 那么我们允许并发执行alpha个slot

那么i+1, i+2, ..., i+alpha都不必等待前一个slot变为chosen, 而是并行地写入, 比如i+3这个位置可能先于i+1变为chosen了(可能因为网络问题)

.. code-block::

            all_chose_index
    1, ...., i,               i+1, i+2, i+3,      i+4,   ..., i+alpha
                                        chosen    chosen

假设位置i-1是all_chosen_index, reconfiguration在位置i写入, 那么i+alpha-1这些位置使用的还是老的configuration, i+alpha位置就必须等待i变为chosen

一旦位置i变为chosen, 那么i+alpha就开始使用新的configuration来写入了.

如果alpha设置为1, 在位置i变为chosen之前, 所有后续的slot都不能写入, 如果alpha很大, 那么reconfiguration生效时间就很久, 所以我们需要把alpha设置为一个和实际相关的值

**这里, 位置i+alpha之后的configuration和之前的位置的configuration是不同的, 所以也称Horizontal Paxos**

reconfiguration pipeline stall
-------------------------------------

如果reconfiguration命令一直阻塞, 比如当前slot的accept返回消息丢失了, 我们需要定时去重发, 那么整个系统就会处于stop the world状态

那么我们的pipeline就是在i+alpha处停止, 这样依赖于前面命令导致后续命令阻塞的现象称为pipeline stall







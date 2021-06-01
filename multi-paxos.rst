
Multi Paxos
##################


1. Paxos Made Simple

2. The Part-Time Parliament

3. https://www.youtube.com/watch?v=JEpsBg0AO6o

4. https://simbo1905.blog/2014/10/28/transaction-log-replication-with-paxos/

5. https://simbo1905.blog/2014/10/05/in-defence-of-the-paxos-consensus-algorithm/

6. https://github.com/allenling/how-redis-cluster-works

7. https://simbo1905.blog/2016/01/02/paxos-uses-leaders-multi-paxos-is-paxos/

8. https://www.youtube.com/watch?v=YbZ3zDzDnrw


使用
==========

启动log server: *python multi_paxos.py node_id log_level*

对于Client, 先启动 *python multi_paxos_client.py*, 然后交互模式下输入命令: choose a


Multi-Paxos和Basic-Paxos的关系
====================================

Basic Paxos证明了如何选择一个值, 并且这个值一旦选择就不能改变. 同时Basic Paxos允许多个Proposer一起发起写入操作, 同时并不影响正确性, 但是会出现活锁的情况

而实际使用中肯定不可能只需要决定一个值, 而是要选择多个值. 典型的使用场景就是log server.

log server把用户的每一个操作记录记录下来, 同时和其他log server同步, 然后执行这些命令. 这样即使一个log server掉线, 那么剩下的log server依然能提供服务同时具有一致性.

从Basic Paxos中延申出, 我们有这样的一个数组, 每个数组的位置称为slot, 那么每个slot就是放置用户命令

.. code-block::

    log data: [None, None, None, ....,]

    log data可能存储用户操作kv数据库的命令

    log data: ["set a=1", "del b", "incr my_number", ..., ]


那么既然Basic Paxos能决定一个值, 那么我们就对每一个slot都执行Basic Paxos算法, 这样每个slot都是一致的, 不可更改的.

这里Paxos Made Simple中提到每个slot都由某个instance执行, 我们就看成每次选择某个slot的时候, 执行一次Basic Paxos算法

.. code-block::

    对下标为index的slot执行一次Basic Paxos算法
    Prepare(pn, index)
    Accept(pn, index, value)

而这个instance可以先直白地理解为, 每个slot我们都为其创建一个Basic Paxos对象实例, 当需要执行的时候, 调用该实例就好了. 或者把instance理解为线程也可以.

总之, instance是和slot绑定的, 要决定某个slot的时候, 就要执行该slot对应的instance


.. code-block::

    一个简单的例子
    instance_map = {0: instance0, 1: instance1, ...}
    要决定slot=5, 那么拿到slot=5对应的instance
    instance = instance_map[5]
    instance.Prepare(pn, index)
    instance.Accept(pn, index, value)

显然, 在实际中不可能这么操作.


Leader
------------

虽然活锁不影响正确性, 但是活锁却影响了性能. 所以Paxos Made Simple中提出了需要一个Leader. 该Leader负责向其他节点同步

客户端写入的时候需要和Leader交互(其他节点可以把写入操作重定向到Leader), Leader来执行Multi Paxos.

在参考5和7中, 分析了Multi Paxos使用Leader的论据.

既然有Leader, 那么我们就需要选举过程. 但是在Paxos Made Simple中并没有提到具体的选举过程, 只是提到了

选举可以很容易地基于timeout和随机化来实现, Paxos Made Simple重点在论证Paxos算法, 选举不是重点, 所以算是给读者的一个练习

**我们可以参考redis cluster的选举流程来实现一个简单的选举过程**


优化流程
--------------

我们不会逐个instance执行, 这样效率太低了. Paxos Made Simple中提到, 我们只需要Leader执行一次Prepare, 这次Prepare是面向所有的slot的

其实理解起来就是所有的slot共享了Proposal Number. 当Leader执行一次Prepare, 向节点传播Proposal Number的时候

每个节点中所有的slot的Proposal Number就提升为收到的Propsal Number. 然后Leaer要向某个slot写入的时候, 直接发送Accept请求就好了.

**Multi Paxos的性能最重要的点就是一次Prepare之后, 写入只需要调用Accept就好了, 而不是每个slot都执行一次Prepare-Accept**

具体论据请看参考5和参考7


基本思路
===========

基本原则: 不要假定网络速度, 比如假定消息在某个什么时候会收到, 有可能永远收到不, 有可能延迟

0. lamport中提到选举是需要基于timeout的, 同时不依赖全局时钟, 可以只依赖本地时钟

   **redis cluster自己有一个简单可用的, 基于timeout和随机退避的方法**

1. 使用curio这个async库去处理IO.

   这个方式在使用上, 理解上比起线程更简单, 比起线程模式, 我们(几乎)不需要处理同步操作, 因为在进入await之前, 永远都是当前coroutine在执行

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

   不相交集合的公式为S(N, n)=(2N-1)*(2**n), 比如第一个集合为S(1, n)=2**n, {2, 4, 8, 16, ..., }, n>=1, 第二个集合为S(2, n)=3*(2**n), {6, 12, 24, 48, ...), n>=1

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

   5.3 socket.send协程, 这个协程主要是把软件中所有的IO操作都放在一个协程内发送, 这样其他协程就不需要操心发送的逻辑了, 只需要把

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

Leader选举
================

这里参考redis cluster的实现, 具体在参考6

**实现选举的时候我们需要实现这样一个程序, 在一个时间段内, 尽量只有一个节点能选举成功, 如果不成功, 那么基于退避原则, 再次发起选举.**

本质上选举就是某个节点发送Prepare请求, 一旦有至少大多数节点返回成功, 那么我们就可以说这个节点就是Leader.

如果有其他节点, 比如B节点, 在A节点发送Prepare之后, 或者A节点发送Accept之后, 又发送了Prepare呢? 如果B节点的Prepare成功, 那么A节点的所有请求都会

失败(没有收到被至少大多数节点返回), 那么A节点将会等待同步, 把自己的Leader提升为B


Gossip消息
-----------------

节点之间使用gossip消息来同步leader信息, 以及判断节点是否掉线

一般来说需要ping/pong, 但是我们其实只需要pong信息, 一旦节点之间相连之后, 各自向其他节点发送pong消息.

pong信息向其他节点发送一下内容:

.. code-block:: python

    {"leader": self.leader, "leader_online": self.is_leader_online(self.leader), "prepare_pn": self.prepare_pn,
     "all_chosen_index": self.all_chosen_index, "leader_prepare_pn": self.leader_prepare_pn}

其中all_chosen_index是和同步消息用的, 后面会说.

leader是自己的leader的node_id, leader_online为True表示自己也检查不到Leader了, prepare_pn则是自己的prepare_pn, 而leader_prepare_pn则是leader的prepare_pn

leader_prepare_pn和prepare_pn不一定相等, 比如

A一开始prepare_pn=-1, leader=None, leader_prepare_pn=-1, 然后B发起Prepare请求, 其prepare_pn为10

A此时有prepare_pn=10, leader=None, leader_prepare_pn=-1, 然后B成为了Leader, 此时

A有prepare_pn=10, leader=10, leader_prepare_pn=10, 然后C发起Prepare, 其prepare_pn为15, 此时

A有prepare_pn=15, leader=10, leader_prepare_pn=10

所以一旦节点自己的prepare_pn大于leader_prepare_pn, 则说明我们进入了一个新的"纪元"(epoch), 和leader不再是一个"纪元"的了

如何判断节点是否掉线?
---------------------------

我们约定如果超过一定时间没有收到某个节点pong消息, 那么我们就说该节点掉线了

.. code-block:: python

    if last_pong_time - now_time < NODE_TIMEOUT * 2:
        nodes[node_id] = OFFLINE

这里我们参考redis cluster, 约定了一个集群的timeout时间NODE_TIME, 作为判断基准, 乘以2是怕网络抖动, 随意设置的

如果节点掉线又在线, 那么我们可以通过pong消息更新状态

.. code-block:: python

    async def handle_pong(self, msg_obj: PongMsg):
        """
        update gossip
        """
        # TODO: save prepare proposal number into file
        from_node = msg_obj.from_node
        self.gossip_msg.update_node_last_pong_time(from_node)
        self.gossip_msg.set_node_online(from_node, msg_obj.get_data())

如果我们通过其他节点发现其他节点和Leader依然相连, 我们可以利用这个级联关系, 让其他节点转发accept给我们而不需要发起Prepare

.. code-block:: python

    async def handle_pong(self, msg_obj: PongMsg):
        self.gossip_msg.am_i_leader(msg_obj.leader) and msg_obj.timestamp - time.time() >= NODE_TIMEOUT:
            logger.info("%s found out leader is still alive from node %s, but we dont do anything for now",
                        self.verbose_name, msg_obj.from_node,
                        )
            # TODO: issue a transmission

现在转发没有实现, 所以只是打印一个消息而已

同时其他节点有可能反复看到leader在线/掉线, 所以我们限制如果经过NODE_TIMEOUT时间之后, 其他节点仍然能连上Leader, 那么此时Leader才会当作是在线的

什么时候发起选举(即Prepare请求)
-----------------------------------

这里发起Prepare的条件是

1. Leader掉线

2. 我们可以和大多数节点相连

3. 其他节点都检测到Leader掉线了

我们每隔NODE_TIME时间去检查一次我们收到的gossip消息, 然后判断是否需要去选举

.. code-block:: python

    async def check_state(self):
        while not self._stop:
            # 每隔NODE_TIMEOUT判断一次
            await curio.sleep(NODE_TIMEOUT)
            # 拿到所有和我们一起还相连的节点, 称为在线节点
            online_nodes = self.gossip_msg.update_nodes_status()
            # 判断其他人是否看到leader
            anyone_see_leader = [i for i in online_nodes if i[1]["leader_online"]]
            # 如果自己不是leader同时leader又掉线了
            if not self.gossip_msg.am_i_leader(self.node_name) and self.gossip_msg.is_leader_offline():
                # 如果我们可以和大多数节点相连, 同时没有人检测到leader在线, 那么随机delay一个时间
                if len(online_nodes) >= self.half and not anyone_see_leader:
                    if self.election_delay_ms == -1 and time.time() - self.last_prepare_time > NODE_TIMEOUT:
                        self.election_delay_ms = random.randint(1000, 3000)  # 1s - 3s
                        logger.info("%s need to start a election, delay %s(ms)", self.verbose_name, self.election_delay_ms)
                        await spawn(self.prepare, daemon=True)


我们发起Prepare之前, 随机delay时间(参考redis cluster)

关于前2个条件可以理解, 而对应第3个条件, 我们先来讨论一下网络分区. 我们简单地把网络分区划分为2种情况

1. 两两之间彻底不相交的, 隔离的, 比如

   {1}, {2}, {3, 4, 5}

   {1, 2}, {3}, {4}, {5}

   {1, 2, 3}, {4, 5}

   {1}, {2, 3, 4, 5}

   这样上述3个条件可以保证只要至少大多数集合, 比如{2, 3, 4, 5}, {3, 4, 5}这些大集合, 没有leader在线, 那么我们就需要发起Prepare

2. 另外一种则是不完全隔离的, 比如

   {1(L), 2}, {2, 3}, {3, 4, 5}, 1是Leader

   这里虽然3和1失去了连接, 但是由于2和3连接, 那么3可以通过2可知leader还在线的, 而4, 5通过3可知leader还在线的

   所以在https://simbo1905.blog/2017/08/22/pre-voting-in-distributed-consensus/, 作者提到既然3和2相连, 而2和leader相连

   那么完全不需要重新Prepare嘛, 直接让2转发leader的accept请求就好了

   但是这里有个情况就是, 你无法假定是{3, 4, 5}之间发起Prepare在前还是3通过2更新自己leader为online在前

   有可能3检测到leader掉线了, 然后发送pong信息给4, 5, 此时, 4, 5可知没有人检测到leader掉线, 所以发起了Prepare请求

   这里有可能我们delay了一段时间, 但是2和3之间的网络延迟, 在4或者5delay之后我们根据3的pong信息发现3依然没有收到2的pong信息, 也就是没有把

   3的leader更新为online状态, 所以4或者5依然发起了Prepare

   所以我们无论这么限制, 网络不可控的, 所以条件3是一个弱条件, 有可能3通过2把自己的leader更新为online, 但是又收到了4或者5的Prepare信息


短时间内有多个节点发起选举呢?
------------------------------------

即使每个节点在发起Prepare之前delay了一段时间, 但是无法控制一段时间内只有一个节点发起Prepare

参考redis cluster, 我们这里会限制在某个时间内, 只回应一个Prepare消息. 这样在一个时间段, 只有一个节点能收到至少大多数节点的回复

.. code-block:: python

    async def handle_prepare(self, msg_obj: PrepareMsg):
        # 
        if time.time() - self.last_prepare_time < NODE_TIMEOUT:
            # prevent too many preparation request coming
            logger.debug("%s got too many prepare msg, ignore prepare msg from node %s",
                         self.verbose_name,
                         msg_obj.from_node)
            return
        self.last_prepare_time = time.time()

我们没记录下上一次收到prepare消息的时间到self.last_prepare_time, 如果在NODE_TIMEOUT时间内, 又收到了一个Prepare消息

我们将不会回应. 同时我们在要发起Prepare的时候, 也判断一下当前时间和self.last_prepare_time的时间差, 如果小于NODE_TIMEOUT, 那么我们也不会发起Prepare

.. code-block:: python

    async def prepare(self):
        if time.time() - self.last_prepare_time < NODE_TIMEOUT:
            logger.info("%s got prepare request at %s, we give up this preparation", self.verbose_name, self.last_prepare_time)
            self.election_delay_ms = -1
            return

升级leader
-----------------


还是{1(L), 2}, {2, 3}, {3, 4, 5}的例子. 这里4会发起Prepare, 然后3, 4, 5将会把leader设置为4

此时2通过3发现, 有一个更大prepare_pn的leader, 意味着其他集合才是大多数集合, 2和1都是处于小部分集合, 显然大集合总是比小集合稳定

所以2将会根据3的pong消息, 升级自己的leader为4

.. code-block:: python

    async def handle_pong(self, msg_obj: PongMsg):
        # 如果pong消息种的prepare_pn或者leader_prepare_pn小于自己的
        # 那么该消息就是无效消息了, 直接返回
        if msg_obj.prepare_pn < self.prepare_pn or msg_obj.leader_prepare_pn < self.gossip_msg.leader_prepare_pn:
            return
        # 如果我们拿到的这个pong消息种, leader_prepare_pn比我们的leader_prepare_pn大
        # 那么我们需要升级自己的leader
        if msg_obj.leader_prepare_pn > self.gossip_msg.leader_prepare_pn:
            logger.info("%s(pn=%s, leader=%s, leader_prepare_pn=%s) upgrade new leader(%s, pn=%s) base on pong from node %s(pn=%s)",
                        self.verbose_name, self.prepare_pn, self.gossip_msg.leader, self.gossip_msg.leader_prepare_pn,
                        msg_obj.leader, msg_obj.leader_prepare_pn,
                        msg_obj.from_node, msg_obj.prepare_pn,
                        )
            self.gossip_msg.leader_prepare_pn = msg_obj.leader_prepare_pn
            self.gossip_msg.set_leader(msg_obj.leader)
            if msg_obj.prepare_pn > self.prepare_pn:
                self.prepare_pn = msg_obj.prepare_pn
            return

如果4在完成Prepare协议之前掉线了, 那么此时, 3, 5都会检测到4掉线

同时5发现自己只能和3一起相连, 那么处于一个小集合, 不会发起Prepare, 而2发先自己和1, 3相连, 同时检测到4掉线, 同时通过3也没发现4在线

所以2可以发起Prepare, 同理3也可以发起Prepare


Takeover协议
===============

通过选举过程, 我们可以说我们总是只有一个leader在线了

根据Paxos协议, 新的Leader必须先同步所有数据才能进行accept操作, 所谓的takeover协议, 步然会出现数据冲突

根据https://cse.buffalo.edu/tech-reports/2016-02.orig.pdf, 提到ZAB和Raft在新leader同步数据上的区别

ZAB会有在选举成功之后(对应我们这里发送Prepare, 然后收到了至少大多数据节点返回, 此时我们可以说我们选举成功了), 那么需要有一个同步阶段, 同步数据, 然后广播同步数据之后才开始写入

而Raft则不会, Raft会在每次写入一个数据之后, replica会发送自己的数据index回给Leader, 然后Leader会再发送需要同步的数据给replcia, 所以Raft选举完成之后就可以执行写入操作了

半同步数据
--------------

**这里我们结合两者的方法, 半同步数据**, 同时这里为了让Prepare过程更清楚, 这里我们引入Prepare Sync阶段.

我们在Prepare Sync阶段只同步Leader自己的数据, 但是不广播给所有的节点, 而是更新我们的数据下标, 我们在pong消息中通过比对数据下标的方式发送同步数据

首先对于log data, 我们保存当前写入的最大下标log_index, 以及所有小于某个下标的slot都是chosen状态, 称这个下标为all_chosen_index

.. code-block::

    log_data: [(value=a, chosen), (value=b, chosen), ..., (value=k, chosen), (value=p, Accepted), (value=None, Empty)]

从a-k, 所有的slot都chosen了, 那么假设k的下标是7, 那么all_chosen_index=7, 同时slot8中的值p处于没有chosen, 而slot9是一个空的slot

所以log_index=9. log_index和all_chosen_index不一样是因为Paxos可以并发地写入, 也就是说slot9不可以不等待slot8变为chosen状态就写入

我们在pong中比对的就是all_chosen_index

Prepare Sync流程
-------------------


1. 发送Prepare, 得到至少大多数节点返回, 那么我们可以说我们是Leader了

   .. code-block:: python

       async def prepare(self):
           prepare_msg = PrepareMsg(self.prepare_pn) # 组装prepare消息
           for node_name in self.nodes_map:
               # 推送给发送协程, 发送消息给所有节点
               await self.send_msg_queue.put((node_name, prepare_msg))
           # 我们将会在MajorityAckEvt这个Event上等待
           self.prepare_ack_evt = MajorityAckEvt(self.prepare_pn, self.half)
           await self.prepare_ack_evt.wait()
           # 如果这个Event.wait返回, 说明要么timeout要么成功了
           logger.info("%s wait prepare status %s", self.verbose_name, self.prepare_ack_evt.status)
           # we may got someone response us with prepare proposal number, so go to check them
           self.prepare_pn = max(self.prepare_pn, self.prepare_ack_evt.get_max_prepare_ack_pn())
           if not self.prepare_ack_evt.is_suc():
               # 如果没有成功, 退出
               return
           else:
               # 进入prepare sync阶段

   收到prepare之后发送prepare ack, 我们收到prepare ack之后, 减少self.prepre_ack_evt的计数, 直到计数为0或者超时

   节点发送prepare ack的时候, 带上自己的log_index和all_chose_index

   如下面所示, 显然我们需要同步的数据就是[a2, b3]这个区间, 所以我们需要节点返回[a2, b3]的数据, 左边界我们称为min_index, 右边界我们称为max_index

   .. code-block::

       all_chosen_index=a, log_index=b
       node1: ---------------a1------------b1---
       node2: --------a2----------b2---
       node1: ------------a3----------------------b3---

2. 发送Prepare Sync消息, 让所有节点返回min_index和max_index之间的数据, 然后Leader取choose每一个slot, 最终[a2, b3]之间的数据都是chosen的

   .. code-block:: python

       def sync_prepare_data(self, prepare_pn, msgs: Sequence[PrepareSyncACKMsg]):

           res = []
           for i in range(len(datas[0])):
               prepare_datas = [j[i] for j in datas]
               # 按prepare_pn由大到小排序
               prepare_datas = sorted(prepare_datas, key=lambda n: -n.prepare_pn)
               # 默认是no_op
               chosen = LogData(prepare_datas[0].pos, value="no_op", req_id=None, state=LogDataState.chosen, prepare_pn=prepare_pn)
               for k in prepare_datas:
                   if k.state == LogDataState.empty:
                       continue
                   # 否则我们选择prepare_pn最大的值作为我们的最终值
                   chosen.value = k.value
                   chosen.req_id = k.req_id
                   break
               res.append(chosen)
           # 更新log_index和all_chosen_index
           self.log_index = max_index
           self.update_all_chosen_index(min_index)

3. 在pong消息中判断节点的all_chosen_index和Leader自己的all_chosen_index, 如果节点的all_chosen_index比较小, 显然我们需要发送同步数据

   .. code-block:: python

       async def handle_pong(self, msg_obj: PongMsg):
           if msg_obj.prepare_pn == self.prepare_pn:
               # 如果我们是leader
               if self.gossip_msg.am_i_leader(self.node_name):
                   # 那么可能需要同步数据了
                   # sync log data
                   self.log_data_manager.may_need_to_sync_chosen(msg_obj.from_node, msg_obj.all_chosen_index)


       def may_need_to_sync_chosen(self, node_name, node_all_chosen_index):
           if self.all_chosen_index is None:
               return
           # 如果节点的all_chosen_index小于自己的all_chosen_index
           if node_all_chosen_index is None or self.all_chosen_index > node_all_chosen_index:
               node_all_chosen_index = node_all_chosen_index or 0
               for pos in range(node_all_chosen_index, self.all_chosen_index+1):
                   # 把数据添加到发送队列, 后面某个时刻我们发送同步数据
                   self.update_chosen_broadcast(node_name, pos, self.log_data[pos])
           return

具体同步的过程在下一节

Accept过程
============


通过选举和takeover过程, 我们能保证稳定情况下只有一个leader负责写入操作. Leader的写入其实就是发送Accept请求而已, 只要写入某个值的时候, 收到至少大多数的节点返回, 那么这个某个值就确定了(chosen状态)

对于client来说, 要写入一个值就是向Leader发送一个choose请求, 而Leader选择下一个log data slot, 发送Accept请求, 一旦收到大多数节点返回成功, 那么向客户端返回成功, 否则返回超时


.. code-block:: python

    async def handle_choose(self, choose_cmd: ClientChooseCmd):

        # 拿到下一个空闲的slot
        log_index = self.log_data_manager.get_next_log_index()
        # 构建msg
        accept_msg = AcceptMsg()
        # 向所有的节点发送accept请求
        for node_name in self.nodes_map:
            await self.send_msg_queue.put((node_name, accept_msg))
        # 在Event上等待
        accept_ack_evt = MajorityAckEvt(self.prepare_pn, self.half, resp_type=MsgType.ACCEPT_ACK)
        self.accept_ack_evts = {log_index: accept_ack_evt}
        # Event返回之后, 判断状态
        if not accept_ack_evt.is_suc():
            # 这里向客户端返回写入超时了
        else:
            # 返回成功给客户端

这里有一个场景就是由于网络延迟, 虽然Leader等待一半的节点返回的时候超时了, 但其实这次的写入操作是成功的

即对于节点N2, N3, 都把这个slot的值设置为accepted状态了, 然后N2的返回Leader收到了, 但是N3的返回Leader已经超时了, 那么显然我们不能把这个slot设置为失败状态, 为什么?

因为如果我们就此把slot设置为no-op, 然后N4收到了把这个slot设置为no-op的请求, 那么如果Leader掉线, N2变为新的Leader之后, 那么N2和N4就出现了冲突.

**也就是说基于超时的话, 我们不能判断其他节点到底是掉线了呢? 还是返回延迟?** 所以我们必须后台一直重发这些超时的accept请求!


后台发送Accept
------------------

这里我们可以合并超时的Accept请求, 不然我们的accept请求有点多啊, 比如我们当前有100个超时的accept, 那岂不是有100个accept请求.

所以我们这里把所有超时的acecpt请求都存到一个列表中, 然后定时去批量发送accept. 这里我们在启动一个后台定时任务, 定时去发送超时的acecpt


.. code-block:: python

    async def handle_choose(self, choose_cmd: ClientChooseCmd):

        # 拿到下一个空闲的slot
        log_index = self.log_data_manager.get_next_log_index()
        # 构建msg
        accept_msg = AcceptMsg()
        # 向所有的节点发送accept请求
        for node_name in self.nodes_map:
            await self.send_msg_queue.put((node_name, accept_msg))
        # 在Event上等待
        accept_ack_evt = MajorityAckEvt(self.prepare_pn, self.half, resp_type=MsgType.ACCEPT_ACK)
        self.accept_ack_evts = {log_index: accept_ack_evt}
        # Event返回之后, 判断状态
        if not accept_ack_evt.is_suc():
            # 这里向客户端返回写入超时了
            # 这里其实就是把某个slot设置为accepted状态, 然后加入到带重试队列中
            self.log_data_manager.mark_timeout_and_need_retry(log_index, value, req_id, self.prepare_pn)
        else:
            # 返回成功给客户端


    # 定时任务发送accept
    async def background_batch_accept(self):
        while not self._stop:
            await curio.sleep(NODE_TIMEOUT + random.randint(1000, 2000) / 1000)
            if not self.gossip_msg.am_i_leader(self.node_name):
                continue
            # 定时从log data中拿到需要重试的slot
            batch_data = self.log_data_manager.get_retry_accept_list()
            logger.debug("background_batch_accept %s", batch_data)
            if not batch_data:
                continue
            # 构建msg
            msg = BatchAcceptMsg()
            msg.set_data(batch_data)
            msg.set_prepare_pn(self.prepare_pn)
            msg.set_from_node(self.node_name)
            # 向所有节点发送
            for node_name in self.nodes_map:
                await self.send_msg_queue.put((node_name, msg))
        return


    # 如果收到batch accept的返回之后, 把这些slot批量设置为chosen状态

    async def handle_batch_accept_ack(self, msg: BatchAcceptAckMsg):
        # 简单地, 把这些slot都标识为chosen
        self.log_data_manager.update_from_batch_accept_ack(self.prepare_pn, msg)
        return


Client和Learner
===================


在Paxos中还有个角色叫Learner, 目前并没有讨论. 先考虑一下这个情况

客户端进行choose, 比如写入这条操作命令cmd="incr COUNT", 如果Leader发送accept, 要么成功, 要么超时失败, 失败超时有可能因为网络延迟导致这次accept ack超时, 此时有两种情况

1. 其他节点已经接受了这个accept请求, 但是网路原因导致accept ack失败

2. 其他节点确实没有收到这个accept请求, 或者只有一小部分的节点接受了这个accept请求.

   但不管怎么样, 这里最后结果就是这个slot不会被新的Leader给感知到有值是accepted的

无论如何, 我们需要在后台一直发送这个accept请求. 此时Leader掉线, N2称为新的Leader, 在上面2情况下, 我们有

1. N2直到slot有值已经是accept的, 所以这个slot的值就是"incr COUNT"

2. 这个slot被标识为no-op

此时Client连接老的Leader, 发现掉线, 那么Client可能就直接重新发起写入操作, 从而导致同样的命令会被执行2次

1. client C1发送命令incr key=a

2. leader L1 发送accept(pn=10, index=15, value="incr key=a")给所有的节点, 此时节点2, 3收到accept

   发送accept_ack

3. 网络原因, L1没有收到2, 3的accept_ack, 然后通知C1此次写入失败(超时)

4. L1掉线, N2被选举为新的leader L2, 然后L2发现index=15中已经accpet了"incr key=a", 那么选择这个incr命令作为index=15的最终值

5. 然后L2, 和3都执行该命令, 此时a从21变为了22

6. C1再次发送写入操作, 然后a就被incr了2次


所以Client在写入之前需要直到这条命令是否已经被写入了, 或者说Leader在发起写入操作的时候, 需要直到这条命令是否被写入了, 我们需要Learner这样的角色!

其实在Paxos的论文中, 一个值是否被chosen是通过Learner来决定的, Acceptor把accept请求发送到Learner, Learner通过这些信息判断是否某个值被大多数Acceptor给接受了, 然后记录下chosen的值

只是之前我们把Proposer和Learner的角色合并了, Acceptor把accept的结果返回给Proposer, 所以Proposer直到哪些值被chosen了

这里我们依然把Proposer和Learner合并起来, 或者说把Proposer, Acceptor, Learner三者都实现在同一个实例中, choose完成之后, 我们Leader还充当Learner的角色

把chosen的值广播给其他所有的节点


所以我们还需要支持查询功能, 根据参考视频3中提到的方法, 在Client发送choose请求给Leader之前, 生成一个request_id, 发送给Leader, 然后每次Leader会记录下request_id是否成功

Leader写入之前查询该request_id是否成功, 或者Client查询是否成功再决定是否发起choose请求.


我们这里启动后台定时任务, 定时把chosen的值广播到其他节点. 这里会出现这样的情况, 我们广播slot3, 4, 5都chosen了给节点N2, N3, N2返回成功, 那么下一次广播给N2的时候就去掉slot3, 4, 5

然后接着slot6, 7, 8变为chosen了, 那么把slot6, 7, 8发送给N2, 而N3对于slot3, 4, 5没有返回, 那么下次就把slot6, 7, 8合并一起, 把slot3, 4, 5, 6, 7, 8发送给N3, 也就是合并发送

.. code-block:: python

    # 后台定时发送batch chosen
    async def background_batch_chosen(self):
        while not self._stop:
            st = NODE_TIMEOUT + random.randint(1000, 2000) / 1000
            await curio.sleep(st)
            if not self.gossip_msg.am_i_leader(self.node_name):
                continue
            # 拿到需要广播chosen的信息
            batch_chosen_data = self.log_data_manager.get_chosen_broadcast_list()
            logger.debug("background_batch_chosen %s", batch_chosen_data)
            # 广播一下
            for node_name in batch_chosen_data:
                if not self.gossip_msg.is_node_online(node_name):
                    continue
                msg = BatchChosenMsg()
                msg.set_from_node(self.node_name)
                msg.set_prepare_pn(self.prepare_pn)
                msg.set_data(batch_chosen_data[node_name])
                await self.send_msg_queue.put((node_name, msg))
        return


    # 其他节点返回batch chosen ack
    async def handle_batch_chosen_ack(self, msg: BatchChosenAckMsg):
        if not self.gossip_msg.am_i_leader(self.node_name):
            logger.warning("im(%s) not the leader(%s), but got a batch chosen ack from %s",
                           self.verbose_name, self.gossip_msg.get_leader(), msg.from_node)
            return
        if msg.prepare_pn < self.prepare_pn:
            logger.warning("%s(pn=%s) got a batch chosen ack with smaller pn %s from %s",
                           self.verbose_name, self.prepare_pn, msg.prepare_pn, msg.from_node)
            return
        # 这里如果节点2返回slot3, 4, 5成功了, 那么我们就把slot3, 4, 5从N2的batch chosen列表中剔除
        self.log_data_manager.update_from_batch_chosen_ack(msg)
        return


    async def handle_choose(self, choose_cmd: ClientChooseCmd):
        # 写入之前查询该命令是否已经写入成功了
        req_id_state = self.log_data_manager.get_req_id_state(req_id)
        if req_id_state == LearnState.suc:
            # 成功就不需要再写入了
            resp.set_status_fail()
            resp.set_reason("request was success, do not issue again!")
            return resp.get_bytes()
        elif req_id_state == LearnState.timeout:
            # 如果之前timeout了, 那么我们肯定再后台一直发送accept, 也不需要再次发送accept
            resp.set_status_fail()
            resp.set_reason("request is waiting for chosen, do not issue again!")
            return resp.get_bytes()


Reconfiguration
=========================

目前为止, 我们都是假设集群的节点不变, 也就是不能向集群添加节点, 或者删除集群中的某个节点, 添加删除操作就是reconfigure的过程, 实际使用中必然需要这样的操作.

按照Paxos Made Simple的思路, 是使用paxos本身去支持reconfiguration, 但在这里https://jaylorch.net/static/publications/smart.pdf 提出Paxos Made Simple本身的思路

太过于简单, 有挺多问题, 工程实现的时候需要考虑很多细节, 而提出了一个基于clone的实现, 称为SMART协议. 后续会实现SMART协议


其他Reconfiguration还有Vertical Paxos, UPaxos等等变种




Cheap Paxos
#################

1. https://lamport.azurewebsites.net/pubs/web-dsn-submission.pdf

2. https://patents.google.com/patent/US7856502B2/en

2中有图片中有详细的流程图解

Dynamic Paxos
===================

Dynamic Paxos是用来修改节点集合的, 也就是执行reconfiguration的, 这里思路就是Paxos Made Simple详细版本, 也就是Horizontal Paxos

同时也提到这里假设同时只有一个节点失败/掉线

In most systems, simultaneous failures are much less likely than successive ones.

然后还提到

One would probably not use **so naive an algorithm as the one just described**. Instead, one would use a more sophisticated algorithm, tuned
for the particular system.

所以这里不太需要详细了解

辅助的节点
=============

Cheap Paxos的重点在于把acceptor的数量从2F+1, 减少到F+1, 剩下的F则是一些辅助性的节点. 比如一共有5个节点, 那么就有2个辅助节点, 以及3个主节点

(这里把辅助节点称为Master节点, 用M来替代, 主节点为acceptor, 用A来替代, Leader用L来表示)

.. code-block::

    M      M

    A1(L)     A2    A3

当我们写入一条命令的时候, Leader节点A1只需要向A2和A3发起accept请求就好了, 辅助节点只需要在选举的时候介入而不需要作为备份的节点

这样辅助节点的消耗会比较小, 可以在一些小型设备之类的设备上实现.

之所以我们在写入命令的时候不需要辅助节点参与, 是因为在prepare和accept阶段, 我们都只需要某个法定人的内的节点响应就可以了, 而不需要所有的节点都响应(参考2中的O2)


法定人数
===============

如果我们想把所有的主节点当作一个有效的法定人数集合, 同时考虑到法定人数的要求是任何两个法定人数集合都相交

那么由此我们需要把法定人数定义修改为 **至少包含大多数节点, 同时包含至少一个主节点, 但这不是绝对的**

在参考2中的例子, 节点11-15, 其中14, 15是辅助节点, 那么文中给出了所有可能的法定人数集合

.. code-block::

    devices 11, 12, 13
    devices 11, 12, 15
    devices 12, 13, 14
    devices 11, 12, 13, 14
    devices 11, 12, 14, 15
    devices 12, 13, 15
    devices 11, 12, 13, 15
    devices 11, 13, 14
    devices 12, 13, 14, 15
    devices 11, 12, 13, 14, 15
    devices 11, 13, 15
    devices 11, 14, 15
    devices 11, 12, 14
    devices 11, 13, 14, 15
    devices 12, 14, 15
    devices 13, 14, 15


因为我们在写入阶段只需要发送请求给主节点, 那么显而易见, 当需要重新选举的时候, 我们必须要知道之前leader写入的命令是什么, 自然需要至少一个主节点被包含在任意一个法定人数当中.

**在这个情况下, 其实我们可以简单的看成法定人数要求是至少包含大多数节点就可以了, 因为至少包含大多数节点这个条件隐含了至少包含一个主节点!**

为什么要大多数?
--------------------------

因为我们写入的时候只发送请求给主节点, 那么如果新的leader能通过某个主节点知道上一个leader的写入命令就可以了

**那么我们能不能只要求每个法定人数至少包含一个主节点, 或者一个主节点和任意一个辅助节点就可以了?**

这是不行的, 如果不要求大多数节点而只要求至少包含一个主节点, 那么无法达到任意两个法定人数必须相交的条件, 比如

节点集合从{11, 12, 13, 14, 15}变为{11, 12, 14, 15}, 13失败了, 被leader节点11提出了集群, 那么如果不要求大多数的, 只要求至少包含一个主节点就可以的话

{11, 14}和{12, 15}这两个集合都可以算是有效的法定人数集合, 但是两者不相交, 这会导致11和12各自都能写入命令而冲突, 或者12无法知道11之前写入的是什么命令而冲突

**这个条件也是Multi Paxos中要求的, 所以这里其实法定人数约束并没有变化, 只是提出我们能指定发送到某个具体的法定人数集合就可以了!**

比如Multi Paxos中要求是至少大多数节点响应, 那么我们需要把请求发送给所有的节点, 然后收到返回的时候判断是否满足条件

而这里的区别就是我们只需要把请求发送给指定的法定人数集合, 比如所有的主节点, 而不需要把请求发送给所有的节点!!!


只有一个主节点的情况
---------------------

如果只有一个主节点, 那么我们的法定人数条件就变成了任何包含该主节点的的集合, 这是因为此时该主节点就变成了任何法定人数的交集!!!!

这样满足了任何法定人数都相交的必要条件


Reconfiguration
========================

因为leader只会把请求发送给主节点(所有主节点集合也是一个法定人数), 那么显然一旦有某个节主节点掉线/失败/连接不上之后, 剩下的主节点已经无法

形成一个法定人数了, **这个时候我们需要选择一个新的法定人数才能继续写入命令.**

在参考2中的例子, 节点12失败, 那么显然{11, 12, 13}这个法定人数无效了, 那么我们可以选择{11, 13, 14, 15}, 或者{11, 13, 14}, 甚至{11, 14, 15}等

这些这个法定人数来继续执行写入操作. **其实我们可以看到, 节点12掉线之后, 所有包含节点12的法定人数都无效了**

主节点掉线后依然可以写入
-------------------------

在参考2给出了一个详细的流程(图8.a开始)

例子中11, 12, 13是主节点, 14, 15是辅助节点, 在一开始假设所有主节点都是正常工作, 那么辅助节点不需要参与到accept流程

.. code-block::

    13(L)  11  12

           14(M) 15(M)


之后节点12由于掉线, 崩溃, 或者网络问题等, 导致13无法得到12的accept返回, 那么此时13无法决定写入成功, 所以选择一个新的法定人数去写入当前命令

在例子中, 13向所有的辅助接点, 也就是14和15发送accept请求, 14和15收到请求之后, 返回成功给13, 那么此时13就得到了

11, 14, 15的返回, 这个一个有效的法定人数集合, 那么13就可以决定说写入成功.

.. code-block::

          <---accept--->  11
    13(L) <---accept--->  14
          <---accept--->  15

**此时辅助节点的作用就是保证系统在主机点掉线之后依然能正常运行**

这里即使14不回应13的请求, 那么此时13还是收到了11, 15的返回, 此时{11, 13, 15}同样也是一个合法的法定人数, 那么依然可以继续写入

同样, 即使12, 11都不回应, 那么{13, 14, 15}同样也是一个合法的法定人数, 那么13还是可以继续写入数据的!

In fact, even if one of the devices 11 and 13-15 had not responded, the remaining three devices also constitute a quorum that is
one of the selected quorums, as evidenced by the listing of Table 1, and the leader could have relied on that quorum to
determine that the proposal was selected.

.. code-block::

          <---accept--->  11
    13(L) <---X-------->  14
          <---accept--->  15

          <---accept--->  11
    13(L) <---accept--->  14
          <---X-------->  15

          <---X-------->  11
    13(L) <---accept--->  14
          <---accept--->  15


选择新的节点集合
-------------------

此时我们需要把12从法定人数集合中踢出, 因为我们希望{11, 13}能继续组成一个合法的法定人数. 那么我们就要修改所有的节点数, 不包含12, 也就是要进行configuration

参考2中的图9.a

leader节点13向辅助节点和主节点11发送一个reconfiguration命令, 这个命令是通过Paxos算法本身来实现的

reconfiguration命令的值包含了不包括失败节点12的所有节点{11, 13, 14, 15}, 发送给11, 14, 15

然后11, 14, 15都知道了节点集合的变更, 此时所有有效的法定人数集合为

.. code-block::

    devices 11, 13
    devices 11, 13, 15
    devices 11, 14, 15
    devices 11, 13, 14
    devices 11, 13, 14, 15
    devices 13, 14, 15

如果reconfiguration的命令在slot下标i位置, 那么reconfiguration完成之前, 13最多能写入a个值(也就是下标为i+a), 也就是configuration变更是水平方向的(horizontal)

在得到一个法定人数集合返回之后, 13就知道节点集合变更了, 那么之后13就会把请求发送到11就好了

注意这里的法定人数集合是{11, 12, 13, 14, 15}的某个合法的法定人数集合而不是{11, 13, 14, 15}, 因为此时reconfiguration并没有完成

这里为了让11尽快的确认configuration成功, 13可以发送一个命令让11知道configuration变更成功了(也就是chosen过程)

而辅助节点14, 15没有必要一定需要收到这个chosen消息


**添加节点和删除节点类似, 只是发送一个reconfiguration命令更改节点的集合而已**


辅助节点的优化
================

在上面的过程中, 辅助节点有写入需求的是在reconfiguration完成之前, 为了维持系统运转, leader需要复制设备发起accept请求

一旦reconfiguration完成, 那么辅助节点显而易见可以丢掉这些命令, 所以需要leader通知复制节点, 可以丢掉1, ..., j的写入信息了

比如当12发生错误的时候, 此时slot下标为i, 那么当reconfiguration执行的时候, 辅助设备需要记录下i, ..., j的消息

一旦reconfiguration完成, 那么leader将会把j之后的写入发送到新的主机点集合, 那么辅助节点就需要记录下当前最大的complete的slot为j, 然后删除掉所有命令

**此时辅助节点参与reconfiguration的时候, 就是一个主机点, 所以正确性什么和Multi Paxos一样**

更进一步, 辅助节点不需要写入命令, 而是记录下命令的hash值就好了, 这样进一步减轻了辅助节点的写入负担.

**但是如果辅助节点只保存了写入命令的hash值而不是真的值, 那么在处理网络分区和liveness条件的时候, 就有区别了**

在参考1中的O4提出:

If that happens, the leader cannot execute its Phase2a action until it communicates with some process that knows v.

也就是说(新)leader如果只直到某个命令的hash而不知道其值, 那么leader不能继续执行2a阶段, 必须等待能和其他节点交流得到该hash的值之后才可以继续写入


网络分区，liveness和正确性
==============================

Cheap Paxos中的法定人数依然是大多数, 所以其网络分区的处理和Multi Paxos一样

依赖于辅助节点参与到reconfiguration的时候, 可以看成一个主节点, 那么对于网络分区我们可以使用pong消息同步等机制去确保不会同时有两个leader存活

正确性也是依赖于同一时间只有一个leader存活.

但是我们考虑一下这个情况, 如果辅助节点只保存了命令的hash值而不是真正的值, 那么有节点{1, 2, 3, 4, 5}, 4, 5是辅助节点而1是leader

1和2, 3都丢失了连接, 此时slot下标为i, 那么根据之前的流程, 1依然能写入, 只是把configuration从{1, 2, 3, 4, 5}修改为{1, 4, 5}

.. code-block::

          4     5

          1      2, 3

同时4和5在1修改configuration的时候记录下了写入命令的hash, 然后

1. 2和3通过4, 5直到1还存活, 可以不去抢占leader

2. 如果1在修改configuration之前掉线了, 此时1已经写入了a个命令, 那么这个a个命令(i到i+a之间)在4和5中只有hash值

   而2和3通过4和5知道1掉线了, 那么当新的leader被选举出来, 假设为2, 那么2是不知道这a个命令的值的, 只知道其hash

3. 如果1在修改configuration之后掉线, 1掉线之前1已经成写入了j-i个消息, 然后1通知4和5, 1, ... ,i , ..,j这些slot已经是chosen了, 那么4和5就删除所有记录的hash

   然后2被选举被新的leader, 同样, 2并不知道i到j之间的值的


在参考1中提到, leader可以在收到所有主节点的2a返回(也就是所有的主节点都收到该accept请求), 才会把hash发送给辅助节点

This is done by having the leader delay sending a “2a” message with the hash of a value v to any
auxiliary processor until all the working main processors have acknowledged receipt of their “2a” messages containing v.

但是这样也不会有太大作用, 考虑这样的情况, 1已经把configuration从{1, 2, 3, 4, 5, 6, 7}修改为{1, 2, 5, 6, 7}了

.. code-block::

          5    6   7

          1,2      3,4

此时3和4通过5, 6, 7知道1还存活, 不抢占leader权限, 但是1和2失败之后, 3和4就不知道1的某些写入命令了, 只知道1到j这个位置的只是chosen的

所以参考1提到Cheap Paxos的liveness条件是

有一个leader, 同时有一个知道所有命令的主节点, 存在一个合法的法定人数集合

The system makes progress if there is a nonfaulty set of processors containing a unique leader, at least one up-to-date main processor, and,
for all active command numbers i, a quorum for instance i of the consensus algorithm.

这样3和4是不能进行操作的, 因为即使3和4中有一个被选举为leader, 同时{3, 4, 5, 6, 7}也是一个有效的法定人数(针对集合{1, 2, 3, 4, 5, 6, 7}来说)

但是不存在一个update-to-date的主节点, 所以如果2能和3, 4相连, 那么才能继续整个算法流程






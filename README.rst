Paxos!
################

稍微理解一下"一致性"

1. http://zhangtielei.com/posts/blog-distributed-consistency.html
2. http://zhangtielei.com/posts/blog-distributed-strong-weak-consistency.html
3. http://zhangtielei.com/posts/blog-distributed-causal-consistency.html
4. http://zhangtielei.com/posts/blog-time-clock-ordering.html
5. https://wudaijun.com/2018/09/distributed-consistency/

这里主要是非拜占庭Paxos及其变种的实现

1. https://vadosware.io/post/paxosmon-gotta-concensus-them-all/#generalized-paxos-in-a-single-reductive-sentence

   关于Paxos各个变种的一些小结

2. https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-935.pdf

   关于Paxos中quorum优化的发展


Basic Paxos
===============

basic_paxos.rst

最基础的paxos实现, 分3个角色, 分别是proposer, acceptor和learner

**这里是实现了basic paxos, 同时解释了paxos正确性的归纳法和反证法过程**

Multi Paxos
================

multi_paxos.rst

Multi Paxos是真正被广泛借鉴的算法

**这里实现了简单的选举, 分区检测等功能, 一个完整的multi paxos实现.**

Dynamic(Horizontal) Paxos
------------------------------

使用Paxos本身去执行reconfiguration, 把reconfiguration的命令也当作一个普通命令写入到slot中, 那么

假设reconfiguration命令是在位置i写入, 那么位置i+alpha之后的configuration和之前的位置的configuration是不同的, 所以称为水平方向的重新配置

**这里并没有实现Horizontal Paxos, 因为这种方式问题比较多(在SMART协议中有提到)**

Flexible Paxos
==================

flexible_paxos.rst

法定人数集合一定要是大多数吗? 答案是并不是, Lamport意识到了(见下面), 而FPaxos提出了法定人数集合的划分方法, 同时我们只需要向特定的法定人数节点发送请求就可以了

法定人数不再是必须需要由大多数节点组成了, 而是区分出了选举和写入两个阶段, 每个阶段的法定人数可以根据需要选择, 只是需要满足一定的约束就可以了

**这里实现了文中提到的majority, simple和grid三种法定人数选择策略**

Cheap Paxos
============================================

cheap_paxos.rst

Cheap Paxos中引入了辅助性设备(Auxiliary Device)的概念

提出我们可以在prepare和accept阶段都可以把请求发送到指定的法定人数集合, 而不需要发送给所有的节点(比Flexible Paxos更早)

这样就把节点数量从2F+1, 降低为F+1个主节点和F个辅助节点.

这样F个辅助节点只是 **必要的时候** 参与到协议中, 只需参与到选举阶段, 执行有限的写入操作, 所以称为低耗能的的辅助节点(Cheap!)

同时法定人数的约束变化为, 从需要至少大多数节点才能组成一个有效的法定人数, 变为至少大多数节点 **同时** 至少包含一个主节点

**如果只有一个主节点的情况比较特殊, 任何包含该主节点的节点集合都是有效的, 因为此时那个主节点就i称为了所有法定人数的交集, 这样满足了任何法定人数都相交的必要条件**

这样我们就可以把2a节点的请求只发送到主节点就好了, 提高了写入的性能. **同时如果辅助设备保存的只有写入命令的hash值得话, 对系统liveness有了特别的约束**

Cheap Paxos中还假设没有多个节点同时掉线(In most systems, simultaneous failures are much less likely than successive ones.)

**这里并没有实现Cheap Paxos, 因为其依赖于Horizontal Paxos**


SMART协议
===========

https://jaylorch.net/static/publications/smart.pdf

作者提出Paxos本身reconfiguration(Horizontal Paxos)的思路太过于简单, 有挺多问题, 工程实现的时候需要考虑很多细节

从而提出了一个基于clone-and-replace(自己的看法)的reconfiguration实现, 称为SMART协议



Basic Paxos
###################

1. https://www.youtube.com/watch?v=JEpsBg0AO6o

2. Paxos Made Simple

3. The Part-Time Parliament

4. https://davecturner.github.io/2016/09/18/synod-safety.html


1. 场景: 选择(写入)一个值
============================

假设有多个客户端向想要向一个设备写入多个值, 客户端称为Proposer, 而设备称为Acceptor, Proposer1想要写入值a, 写作P1(a), 如果Acceptor接受了值a, 那么我们写作Acceptor(a)

同时我们写入之后就不能改变了, 也就是说我们可以询问Acceptor接受的是哪个值, 一旦Acceptor接受了值a, 那么之后我们查询写入值总是a


.. code-block::

    P1(a)  ----->

    P2(b)  ----->    Acceptor(a)

    P3(c)  ----->



Acceptor值接受其中一个值, 那么当只有一个Acceptor的时候, 那么显然我们可以让Acceptor只接受第一个值, 无论P1, P2, P3谁的请求先到达Acceptor, 那么Acceptor就接受谁的值

一旦Acceptor接受一个值之后, 就无法改变, 就忽略所有后续的写入操作. 这样我们总是能询问Acceptor是否接受了写入值, 以及写入的值是什么

但是这样有个问题就是因为只有一个Acceptor, 那么显然一旦Acceptor掉线, 那么我们就不能写入任何值(比如在写入之前Acceptor掉线了), 或者不能查询写入的值是多少(比如Acceptor接受某个值之后掉线了)

那么显然我们可以使用多个Acceptor来共同提供写入服务. **所以这里就引出这样的一个问题, 如果使得多个Acceptor能写入同一个值, 并且能容忍某些Acceptor掉线之后依然能进行服务?.**


2. 多个Acceptor如何写入?
============================

这里我们假定多个Acceptor不会交流他们写入的值是什么, Acceptor只接受Proposer的写入请求(当然某个Acceptor可以通过心跳等等去感知其他Acceptor的存在, 但也仅此而已)

既然是有多个Acceptor, 那么当某个Proposer要写入一直的时候, 必须是向多个Acceptor请求写入, 那么如果所有的Acceptor都接受Proposer写入的值, 那么我们就可以说该值被写入了

比如有3个Acceptor, A1, A2, A3, 当P1想要写入值a的时候, 发起请求P1(a), 那么A1, A2, A3都接受a, 那么显然所有的Acceptor都写入了a, 那么显然a就无法改变了, 换句话说

A1, A2, A3都无法再写入任何值, 同时我们查询A1, A2, A3中的任意一个, 都直到写入的值是a, 所以此时所有Acceptor都对写入值达成了共识, 即写入值是a


.. code-block::

    所有的Acceptor都接受了P1写入的值, 那么我们说P1写入成功

          <----> A1(a)

    P1(a) <----> A2(a)

          <----> A3(a)

但是, 我们可以不要求所有的Acceptor都接受a, 而只要求只需要足够多的Acceptor接受了a就能达到共识. 这个足够多是多少, 我们这里约定是大多数, 即假设有3个Acceptor, 那么只需要2个Acceptor接受了

a, 我们就可以说写入成功了. 为什么是大多数, 因为任意2个大多数集合至少有一个元素重合. **当然接受写入的Acceptor个数也不一定是大多数, 但是这里使用大多数作为条件**



.. code-block::

    只有2个Acceptor接受P1写入的值, 我们依然可以说写入成功

                 A1

    P1(a) <----> A2(a)

          <----> A3(a)



3. 如果有多个Proposer怎么办?
==================================


多个Acceptor下我们可以说一旦有大多数Acceptor接受了某个值, 那么我们就说该值被写入了, 但是如果有多个Propser发起(不一定同时)写入请求呢?


因为每个Proposer都会向所有的Acceptor发送写入请求, 那么Acceptor如何决定某个值是否应该被写入?


注意, 这里我们依然是要求只需要大多数Acceptor接受某个值我们就可以说该值被写入了, 或者chosen了

这里假设有5个Acceptor, A1, A2, A3, A4, A5


1. 我们可以让Acceptor只接受第一个值, 而忽略后续所有的值, 这样无法写入任何值, 也就是没有大多数Acceptor接受同一个值.

   比如P1, P2, P3同时发起写入请求给A1-A5, 由于网络延迟, P1请求P1(a)先发送到了A1, A2, 同时P(b)先发送到了A3, A4中

   而P3(c)则先发送到A5中, 这样A1, A2接受a, 而忽略后续的任何值, 这里也就是b和c, 同理A3, A4只接受b, 而A5只接受了c

   这样没有值被写入


   .. code-block::

       P1(a) ----->   A1(a)

                      A2(a)

       P2(b) ----->   A3(b)

                      A4(b)

       P3(c) ----->   A5(c)



2. 既然Acceptor不能只接受第一个值, 那么我们就让Acceptor可以接受任何值, 不仅仅是其第一次收到的值

   但是这样依然不能决定哪个值应该被写入. 假设, P1先向所有的Acceptor发起写入, 而P2后发起写入请求.

   如果P1(a)先被A1, A2, A3接受, 由于网络原因, 在A4, A5没有收到P1(a), 但是我们可以说a已经被写入了, 如果我们此时查询, 就可知写入值是a

   但是过来一段时间, P2向所有Acceptor发起写入请求P2(b), 由于网络延迟等等, P3, A4, A5收到了P2(b), 此时我们可以说b是写入值. 那么

   这里我们就发现有多个值在不同时间被写入了, 也就是等于没有值被写入


   .. code-block::

       在时间t1, 我们可知a被写入了

       P1(a)   -----> A1(a)

               -----> A2(a)

               -----> A3(a)

       在时间t2, 我们知道b被写入了


       P2(b)   -----> A3(b)

               -----> A4(b)

               -----> A5(b)



我们不能让Acceptor只接受第一个收到的值, 也不能接受任何时刻收到的值. 怎么办？ **很直接的方法就是, 一旦一个值被写入, Acceptor就拒绝(忽略)掉所有后续的写入请求**

比如2中, a已经被A1, A2, A3给接受了, 那么显然a已经chosen了, 那么显然A3不应该接受b了, 如果A3不接受b, 那么b就只能被A4, A5给接受, 那么b没有达到大多数的标准, 所以b没有chosen

这也符合我们的目的, 即一旦一个值被chosen之后(也就是被大多数Acceptor给接受了), 那么这个值就不能变了, **所以我们希望知道某个值是否chosen, 一旦chosen, 那么就不能写入任何值了**


4. 预言未来和拒绝过去
=========================

那么A3怎么知道a是chosen了呢? 因为Acceptor之间无法知道其他Acceptor的接受值是什么, 但是Proposer是可以知道的, **所以我们必须要求Proposer一旦知道某个值是chosen了的, 就不能再写入了自己的值了**

比如在上一节中, P2在写入b之前, 先要向所有Acceptor请求一下其接受了哪个值, P2发现a被大多数A1, A2, A3都接受了值a, 那么显然a就是chosen了, 那么显然P2就不能写入b了.

但是这里有个问题, **如果只有A1和A2接受了a, 那么P2就知道只有2个Acceptor接受了a, 那么显然a没有chosen, 但是P2怎么能保证在其发送写入操作之前的某一段时间没有值被chosen呢?**

或者, P2向A3, A4, A5发起询问, 由于网络延迟, A3并没有收到P1(a), 然后P2发现大多数节点都没有接受任何值, 可以发起请求P2(b), 但是在P2(B)到达A3之前, A3收到了P1(a), 这样又回到了上一节例子2的情况

**显然P2无法预言未来某段时间内没有值是否chosen!**


"predicting future acceptances is hard. Instead of trying to predict the future, the proposer controls it by extracting a promise that there
won’t be any such acceptances. In other words, the proposer requests thatthe acceptors not accept any more proposals numbered less than n. This
leads to the following algorithm for issuing proposals."
-- Paxos Made Simple

**所以于其预言未来, 不如拒绝过去.**


也就是说, P2与其预言未来是否有值是chosen, 而是说P2让所有的Acceptor都保证, 而是拒绝所有某些写入请求. 那拒绝掉哪些请求呢？

**我们为每个请求分配一个序号, 我们称为Proposal number, 简写做pn. 我们把询问的阶段称为Prepare, 而正真正写入的阶段称为Accept**


1. 首先, P1在写入之前, 需要先向Acceptor询问它们自己接受的值, 同时带上一个序号, 假设该序号为pn=10

   然后A1, A2, A3发现自己本身的序号为0(或者-inf), 那么必然有10>0(或者-inf)

   所以保证拒绝掉所有小于序号10的请求, 返回成功给P1, 同时A1, A2, A3自己把自己的序号提升为10.

   .. code-block::

       P1发起Prepare
       Prepare(10)   -----> A1(0, NULL)

                     -----> A2(0, NULL)

                     -----> A3(0, NULL)

       A1, A2, A3更新自己的pn, 同时返回NULL给P1

       Prepare(10)   <-NULL---- A1(10, NULL)

                     <-NULL---- A2(10, NULL)

                     <-NULL---- A3(10, NULL)


2. 然后P1发现没有值被写入, 那么发起写入请求Accept(a), 同时带上序号10, A1, A2收到了P1的写入请求, 发现序号不小于自己的序号10, 那么接受值a, 而A3没有收到P1(a)

   .. code-block::

       P1发起Accept
       Accept(10, a)   <-----> A1(10, a)

                       <-----> A2(10, a)

                               A3(10, NULL)

3. 之后P2想要写入值b, 但是同样需要知道是否有值chosen, 那么向所有Acceptor发起询问请求, 此时P2带上序号15, 然后A3, A4, A5收到了P2的询问请求

   显然P4和P5没有接受过任何请求, 其序号为0(或者-inf), 那么接受该请求, 同时把自己的序号提升为15. 而A3发现序号15大于自己的序号10, 那么也返回成功给P2

   .. code-block::

       P2发起Prepare
       Prepare(15)  <-----> A3(15, NULL)

                    <-----> A4(15, NULL)

                    <-----> A5(15, NULL)

4. 此时P2发现没有值被接受, 所以可以发起写入操作, 发起P2(b), 同时带上序号15

   .. code-block::

       P2发起Accept
       Accept(15, b)  <-----> A3(15, b)

                      <-----> A4(15, b)

                      <-----> A5(15, b)

5. 此时P1的Accept(10, a)到达了A3, 那么A3发现其序号10小于自己的序号15, 则拒绝掉此次Accept

   .. code-block::

       P1的Acceptd到达A3
       Accept(10, a)  -----> A3(15, b), A3拒绝



6. 最后, 只有b是chosen了, 而a没有chosen


5. 选择哪个值写入?
=========================

在小节3中提到的例子2中, 如果P1发送的P1(a)被A3给接受了, 而P2发起询问请求给A3的时候, A3发现序号大于自己的序号, 那么返回成功, 同时带上自己已经接受了值a

但是P2不知道A1, A2是否接受了a, 只知道A4, A5没有接受任何值, 而A3接受了a, 所以无法决定a是否chosen了.

.. code-block::

    P1发送Accept, A3接受了a
    Accept(10, a)   <-----> A1(10, a)

                    <-----> A2(10, a)

                    <-----> A3(10, a)

    P2发送Prepare, 发现A3已经接受了a, a是否chosen了呢?
    Prepare(15)    <-----> A3(15, a)

                   <-----> A4(15, NULL)

                   <-----> A5(15, NULL)

**P2发现A3接收了a, 但是A4和A5都没接收任何值, 那P2能选择自己的值b作为写入值吗? 显然不行**

如果a没有被A1, A2给接受, 那么显然P2可以写入b, 因为a没有被大多数Acceptor接收, 但是如果A1, A2都接收了a

那么P2再选择写入b的话, 岂不是有两个值chosen了, 或者说P2改变了chosen值a, 这样不允许的!

5.1 选择最大的值作为写入值
-------------------------------

paxos中提到, 如果没有任何acceptor接受了任何值, 那么我们可以提交任何值. 这个我们可以理解, 但是如果有某些acceptor已经接受了某些值呢?

**我们需要选择已经接收的值中, proposal number最大的那个作为写入的值!!!**

在Paxos Made Simple中, 提到

For any v and n, if a proposal with value v and number n is issued, then there is a set S consisting of a majority of acceptors such that
either (a) no acceptor in S has accepted any proposal numbered less than n, or (b) v is the value of the highest-numbered proposal among
all proposals numbered less than n accepted by the acceptors in S.

对于情况(a), 那么就是所有的acceptor都没有接受过任何值, 那么我们可以接受任何值, 而(b)就是(a)的相反面, 也就是肯定有某些acceptor已经接受了

某些值, 那么我们需要在这些已经接受了某些值得acceptor中, 选择接受的proposal number最大的作为写入值!

假设A3, A4, A5分别接受了pn和值为(10, a), (11, q), (12, k), 那么P2选择proposal number最大的值作为写入值

A3(pn=10, accepted_pn=10, value=a)第一个10表示当前最大的序号为10, 第二个10表示接受值a的时候, 所带上的序号为10

.. code-block::

    P17发起prepare
    Prepare(15)   -----> A3(10, 10, a)

                  -----> A4(11, 11, q)

                  -----> A5(12, 12, k)

    P17收到了(10, a), (11, q), (12, k)返回
    Prepare(15)    <---(10,a)-- A3(15, 10, a)

                   <---(11,q)-- A4(15, 11, q)

                   <---(12,k)-- A5(15, 12, k)

    P17选择序号最大的值作为写入值, 也就是k
    Accept(15, k)   <-----> A3(15, 15, k)

                    <-----> A4(15, 15, k)

                    <-----> A5(15, 15, k)

为什么会出现这样的情况? 因为网络原因

1. P1发送Accept(10, a)的时候, 只有A3收到了请求.

2. P2在发送Prepare(11)的时候, A3没有收到请求但是A1, A2, A4收到了, 然后A2的Accept(11, q)只有A4收到了

3. P3的Prepare(12)只有A1, A2, A5收到了, 然后P3的Accept(12, k)只有A5收到了

4. 最后P17发起Prepare(15), 只有A3, A4, A5收到了

**为什么选择收到的prepare返回中, proposal number最大的值作为写入值? 例子中的(15,k)**

既然收到的prepare返回中, accepted_pn有很多个值, 意味着, 每一轮的prepare都成功了!!!

比如上面的例子中, P1, P2, P3的Prepare都成功了! 那么意味着P2会把P1的Accept给阻止掉, P3会把P2的Accept给阻止掉!

**所以最大的accepted_pn才是最可能chosen的值!! 但是为什么是最可能而不是一定是chosen的值?**

因为最大的accepted_pn的Accept可能也没成功!!, 比如上面例子中的P3, 其Accept会被P17的Prepare给阻止掉!!!

但是P17依旧看到了P1, P2, P3所写入的值, 显然P17不知道P3的写入是否被大多数接受了, 但它知道P3的写入之前, P3的prepare是被大多数确认的!

那么P3很可能写入成功了, 所以必须把P3的k作为写入值, 无论P3的Accept是否成功!

所以我们必须选择accepted_pn最大对应的值作为写入值!!

回到第一个例子

.. code-block::

    P1发送Accept, A3接受了a
    Accept(10, a)   <-----> A1(10, 10, a)

                    <-----> A2(10, 10, a)

                    <-----> A3(10, 10, a)

    P2发送Prepare, 发现A3已经接受了a, a可以是chosen也可以不是chosen, 无论如何, 我们都需要选择a作为写入值
    Prepare(15)    <--(10,a)-------- A3(15, 10, a)

                   <--(NULL,NULL)--- A4(15, NULL, NULL)

                   <--(NULL,NULL)--- A5(15, NULL, NULL)

显然P2要选择a作为写入值, 因为a的accepted_pn=10, 其proposal number最大

Acceptor中的proposal number约束
===============================================

Acceptor是否接受同一个proposal number的Prepare请求? Paxos Made Simple中提到是不可以的(greater than)

"If an acceptor receives a prepare request with number n **greater than** that of any prepare request to which it has already responded,
then it responds to the request with a promise not to accept any more proposals numbered **less than** n and with the
highest-numbered proposal (if any) that it has accepted"

Acceptor是否接受同一个proposal number的Accept请求? 可以的

"If an acceptor receives an accept request for a proposal numbered n, it accepts the proposal unless it has already responded to a prepare
request having a number greater than n."

这里提到it accepts the proposal unless it has already responded to a prepare request having a number greater than n.

也就是说只有收到更大的proposal number的prepare请求才不能接收当前accept, 否则acceptor则直接接受该Accept请求


Basic Paxos协议
======================

1. 协议中有两个角色Proposer和Acceptor(其中还有一个Learner的角色, 这里先忽略但不会影响协议的正确性, 在Multi-Paxos中会提到)

   Proposer是发起写入的角色, 而Acceptor是投票的角色, 只有超过一半(大多数)的Acceptor向某个值投了票, 那么才能说某个值是chosen

2. Paxos是一个两阶段的协议, 首先是一个让Acceptor做出保证不接受任何小于当前序号请求的阶段, 称为Prepare阶段, 以及一个写入阶段, 称为Accept阶段

3. 每次发起新一轮协议之前(也就是执行新一轮的Prepare/Acceptor), Proposer选择一个序号, 即Proposal Nnumber, pn, 作为当前轮的序号

   Acceptor收到任何请求的时候, 首先判断如果请求的pn **是否小于** 自己当前的pn序号, 小于则拒绝该请求

   如果该pn大于自己的pn, 那么更新自己的pn为最新的pn, 这样任何小于该pn的请求都会被拒绝掉!

   Prepare阶段就是为了更新Acceptor的Proposal Number, 拒绝掉所有"老"的请求

4. Basic Paxos是一个多轮的协议, 也就是说P2发现自己发出的Prepare或者Accept请求没有成功, 比如没有得到大多数Acceptor返回

   那么选择一个更大的Proposal number, 继续新的一轮协议

5. 具体的流程请参考视频1


Liveness问题
==================

paxos保证了即使多个Proposal number, 那么一旦有值被chosen, 那么绝对不会被改变, 也就是不影响其正确性

但是有可能没有proposer能写入任何值, 也就是出现了活锁

也就是P1发起Prepare(n)之后, P2发起了Prepare(n1), n1>n, 然后P1发现写入失败, 然后使用一个更大的pn=n3, n3>n2, 发起Prepare, 然后P2写入失败, 又使用

n4, n4>n3来发起Prepare, 最终没有人能写入任何值

Basic Paxos正确性的归纳证明
=============================

Paxos Made Simple的归纳法证明其正确性, 其正确性为不可能有两个值被chosen

一个proposal请求由一个proposal number和一个值v组成, 写作proposal(pn, v), **同时任意两个大多数集合至少有1一个元素重合, 这样非常重要的条件**

1. P2. If a proposal with value v is chosen, then every higher-numbered proposal that is chosen has value v.

   如果一个proposal(n, v)已经是chosen了, 那么任何大于n的的proposal, 其chosen值都是v

   这样就能保证一旦一个值被chosen了就不会改变, 所以就要求所有未来任何chosen的值都是v

   **为什么未来还可以选择一个值为chosen?**

   这是因为Acceptor是可以接受任何 **不小于** 其proposal number的写入操作的

   因为我们总是可以chosen多个值, 所以如果我们希望chosen值, 假设为v, 不能改变, 那么必然有任何未来的chosen的值都等于v

2. P2a. If a proposal with value v is chosen, then every higher-numbered proposal accepted by any acceptor has value v.

   一个proposal(n, v)被认为是chosen, 那么必然有大多数的Acceptor都accept了proposal(n, v), **也就是说chosen依赖于Acceptor的accept行为**

   由P2得出, 一个值是chosen了, 那么未来所有的chosen值都是v, 那么又由于chosen意味着/等同于被大都数Acceptor给accept了

   所以这里说一旦Proposal(n, v)成为chosen, 那么之后所有proposal(ni, vi), ni>n, 都会被大多数Acceptor给accept, 那么要保持

   v == vi, 那么就要求所有的Acceptor执行accept的时候, 值为v

3. P2b. If a proposal with value v is chosen, then every higher-numbered proposal issued by any proposer has value v.

   由于Acceptor依赖于Proposer, 显然又P2a可以推论出, 对于Proposal(ni, vi), ni>n, 有Proposer发送的时候, vi == v

4. P2b如何能保证P2是满足的呢?

   假设v在proposal number为m的时候已经被chosen了, 那么我们需要证明任何n > m, 其chosen的值vn == v

   这里文中使用了归纳法, 里面说明在P2b条件下, 也就是对于所有m, ..., n-1的proposal number, Proposer发起的accept请求, 其值都是v

   所以我们有, m, v已经是chosen了, 对于m, ..., n-1的proposal number中, 所有的Proposer发起的accept的值都是v, 对于proposal number为n, 其chosen的值vi

   由于m, v是chosen的, 那么显然有一个至少包含大多数节点的集合C, 每一个Acceptor都accept了值v

   又由于我们假设了P2b, 那么对于每个m, .., n-1, 我们都发送了v给所有的Acceptor, 也就是

   对于proposal number=i, Proposer发送值为v给所有的Acceptor, 这里能发送proposal请求, 隐含了至少大多数集合响应了i的prepare请求!

   i的proposal请求可能只有一部分Acceptor接收到, 这个收到i的proposal请求的集合为Ci, Ci可能为空

   同理, 对于i+1, i+2, ..., n-1, 我们有集合Ci+1, Ci+2, Cn-1, 所有这些集合如果不为空, 那么其中的Acceptor接收到proposal请求的时候, 值都是v

   那么对于proposal number=n, 我们先发送prepare, 得到大多数Acceptor响应, 此时这个集合为Cn, Cn至少包含大多数集合

   那么显然Cn和Cm, Cm+1, ..., Cn-1至少有一个元素相交, 又由于Cm, ..., Cn-1中所有的值都是v, 那么显然Cn中, 如果Acceptor已经accept了某个值, 那么必然是v

   那么n从Cn得到的信息来看, 要想满足P2, 在n我们必须选择proposal number最大的值作为自己的写入值, 才能保证P2满足

   如果没有acceptor接收过任何一个值, 那么我们可以提交任何值


Basic Paxos正确性的反证法证明
===============================

参考4的翻译了一下, 反证法更好理解一点

如果在P, Q两个时间点, 或者更准确的说, 如果对于两个Proposal number, P和Q, 其中P < Q, 如果P和Q分别chosen了一个值vp, vq, 有没有可能vp != vq

**注意这里的前提条件是vp和vq是chosen的, 这里暗示了这样一个条件, vp和vq分别被P的大多数集合和Q的大多数集合给accept了, 这是最重要的前提!**


.. code-block::

    P,vp                        Q,vq
     .----------------------------.

     vp == vq?

如果vp和vq不相等, 那么在P和Q之间的某个R, 其chosen的值是第一个值不等于vp.


.. code-block::

    P,vp    M      R,vr             Q,vq
     .------------- . ----------------.

     vp == vm
     vp != vr

也就是说对于所有m, P <= M < R, chosen的值都是vp. 既然vp已经chosen了, 那么显然在P, 有一个至少大多数节点的集合accept了vp, 这个集合称为s

对于R, 其要发起accept操作, 那么必然先发起prepare操作, 在R发起prepare操作的时候必然得到至少大多数节点返回

**为什么?**

因为我们在假设种提到在R时间点, 有一个chosen的值vr, 有vr!=vp, 那么显然R的prepare请求必须得到至少大多数节点同意.

因为我们直到大多数集合至少有一个节点相交, 假设这些相交的节点为a, 那么a必然先收到P的accept请求, 然后再收到R的prepare, 这个顺序不可能变

**为什么?**

因为我们再假设在P种chosen的值是vp, 那么a如果先收到R的prepare, 那么a会拒绝掉P的accept请求, 显然会导致vp不能chosen, 这个和假设相矛盾

又由于对于所有的m, P <= M < R, 有vm == vp, 那么对于R, 发送prepare之后, 收到的返回中, 最大proposal number对应的值就是vp

所以对于a, 他们在R之前, 收到的所有accept请求中, 值总是vp, 也就是a最大的proposal number对应的值就是vp

R不仅仅收到a的返回, 也收到其他节点的返回, 这些节点为c, c是和s不相交的部分, c中是否有节点, 接收了大于R的proposal number的请求?

**不可能, 为什么?**

因为我们假设在R这个时间点, 其chosen的值为vr, 那么必然有R会被某个大多数集合给接收, 这些节点如果接收了大于R的proposal number请求的话

那么vr是不可能chosen的, 这与假设相悖

所以c中的所有节点, 收到的accept都小于R, 大于P, 那么显然c中最大proposal number对应的值就是vp, 那么有

vr == vp, 这样于假设相悖. 所以我们得到vp == vq







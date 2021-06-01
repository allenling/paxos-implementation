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

但是这里有个问题, **如果只有A1和A2接受了a, 那么P2就知道, 只有2个Acceptor接受了a, 那么显然a没有chosen, 但是P2怎么能保证在其发送写入操作之前的某一段时间没有值被chosen呢?**

或者, P2向A3, A4, A5发起询问, 由于网络延迟, A3并没有收到P1(a), 然后P2发现大多数节点都没有接受任何值, 可以发起请求P2(b), 但是在P2(B)到达A3之前, A3收到了P1(a), 这样又回到了上一节例子2的情况

**显然P2无法预言未来某段时间内没有值是否chosen!**


"predicting future acceptances is hard. Instead of trying to predict the future, the proposer controls it by extracting a promise that there
won’t be any such acceptances. In other words, the proposer requests thatthe acceptors not accept any more proposals numbered less than n. This
leads to the following algorithm for issuing proposals."
-- Paxos Made Simple

**所以于其预言未来, 不如拒绝过去.**


也就是说, P2与其预言未来是否有值是chosen, 而是说P2让所有的Acceptor都保证, 而是拒绝所有某些写入请求. 那拒绝掉哪些请求呢？

**我们为每个请求分配一个序号, 我们称为Proposal number, 简写做pn**

**我们把询问的阶段称为Prepare, 而正真正写入的阶段称为Accept**


1. 首先, P1在写入之前, 需要先向Acceptor询问它们自己接受的值, 同时带上一个序号, 假设该序号为pn=10, 然后A1, A2, A3发现自己本身的序号为0(或者-inf), 那么必然有10>0(或者-inf)

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


2. 然后P1发现没有值被写入, 那么发起写入请求P1(a), 同时带上序号10, A1, A2收到了P1的写入请求, 发现序号不小于自己的序号10, 那么接受值a, 而A3没有收到P1(a)

   .. code-block::

       P1(10, a)   <-----> A1(10, a)

                   <-----> A2(10, a)

                           A3(10, NULL)

3. 之后P2想要写入值b, 但是同样需要知道是否有值是chosen了, 那么向所有Acceptor发起询问请求, 此时P2带上序号15, 然后A3, A4, A5收到了P2的询问请求

   显然P4和P5没有接受过任何请求, 其序号为0(或者-inf), 那么接受该请求, 同时把自己的序号提升为15. 而A3发现序号15大于自己的序号10, 那么也返回成功给P2

   .. code-block::

       Prepare(15)  <-----> A3(15, NULL)

                    <-----> A4(15, NULL)

                    <-----> A5(15, NULL)

4. 此时P2发现没有值被接受, 所以可以发起写入操作, 发起P2(b), 同时带上序号15

   .. code-block::

       P2(15, b)  <-----> A3(15, b)

                  <-----> A4(15, b)

                  <-----> A5(15, b)

5. 此时P1(a)到达了A3, 那么A3发现其序号10小于自己的序号15, 则拒绝掉此次P1(a)

   .. code-block::

       P1(10, a)  -----> A3(15, b)



6. 最后, 只有b是chosen了, 而a没有chosen




5. 选择哪个值写入?
=========================


在小节3中提到的例子2中, 如果P1发送的P1(a)被A3给接受了, 而P2发起询问请求给A3的时候, A3发现序号大于自己的序号, 那么返回成功, 同时带上自己已经接受了值a

但是P2不知道A1, A2是否接受了a, 只知道A4, A5没有接受任何值, 而A3接受了a, 所以无法决定a是否chosen了.


.. code-block::

    A3接受了a

    P1(10, a)   <-----> A1(10, a)

                <-----> A2(10, a)

                <-----> A3(10, a)

    P2发现A3已经接受了a, a是否chosen了呢?

    Prepare(15)    <-----> A3(15, a)

                   <-----> A4(15, NULL)

                   <-----> A5(15, NULL)


**P2发现A3接收了a, 但是A4和A5都没接收任何值, 那P2能选择自己的值b作为写入值吗? 显然不行**

如果a没有被A1, A2给接受, 那么显然P2可以写入b, 因为a没有被大多数Acceptor接收, 但是如果A1, A2都接收了a, 那么P2再选择写入b的话, 岂不是有两个值chosen了, 或者说P2改变了chosen值a, 这样不允许的

Paxos要求P2选择a作为P2要写入的值而不是P2本来的值b, 也就是说以防万一, a很可能已经被大多数Acceptor给接受了, 比如A1, A2, A3.

或者说我们会根据proposal number做出选择, 假设A3, A4, A5分别接受了pn和值为(10, a), (11, q), (12, k), 那么P2选择proposal number最大的值作为写入值

A3(10, 10, a)第一个10表示当前最大的序号为10, 第二个10表示接受值a的时候, 所带上的序号为10


.. code-block::

    P2发起询问

    Prepare(15)   -----> A3(10, 10, a)

                  -----> A4(11, 11, q)

                  -----> A5(12, 12, k)

    P2收到了(10, a), (11, q), (12, k)返回

    Prepare(15)    <---(10,a)-- A3(15, 10, a)

                   <---(11,q)-- A4(15, 11, q)

                   <---(12,k)-- A5(15, 12, k)

    P2选择序号最大的值作为写入值, 也就是k

    Accept(15, k)   <-----> A3(15, 15, k)

                    <-----> A4(15, 15, k)

                    <-----> A5(15, 15, k)

为什么? 在下面证明给出


Basic Paxos协议
======================

1. 协议中有两个角色Proposer和Acceptor(其中还有一个Learner的角色, 这里先忽略但不会影响协议的正确性, 在Multi-Paxos中会提到)

   Proposer是发起写入的角色, 而Acceptor是投票的角色, 只有超过一半(大多数)的Acceptor向某个值投了票, 那么才能说某个值是chosen


2. Paxos是一个两阶段的协议, 首先是一个让Acceptor做出保证不接受任何小于当前序号请求的阶段, 称为Prepare阶段, 以及一个写入阶段, 称为Accept阶段


3. 每次发起新一轮协议之前(也就是执行新一轮的Prepare/Acceptor), Proposer选择一个序号, 即Proposal Nnumber, pn, 作为当前轮的序号

   Acceptor收到任何请求的时候, 首先判断如果请求的pn是否小于自己当前的pn序号, 那么拒绝该请求

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


Paxos Made Simple的归纳法

一个proposal请求由一个proposal number和一个值v组成, 写作proposal(pn, v), **同时任意两个大多数集合至少有1一个元素重合, 这样非常重要的条件**


1. P2. If a proposal with value v is chosen, then every higher-numbered proposal that is chosen has value v.

   如果一个proposal(n, v)已经是chosen了, 那么任何大于n的的proposal, 其chosen值都是v

   这样就能保证一旦一个值被chosen了, 那么不会改变, 所以就是所有未来任何chosen的值都是v

   为什么未来还可以选择一个值为chosen, 这是因为Acceptor是可以接受任何不小于其proposal number的写入操作的

   因为我们总是可以chosen多个值, 所以如果我们希望chosen值, 假设为v, 不能改变, 那么必然有任何未来的chosen的值都等于v


2. P2a. If a proposal with value v is chosen, then every higher-numbered proposal accepted by any acceptor has value v.

   一个proposal(n, v)是chosen, 必然有大多数的Acceptor都接受(accept)了proposal(n, v), 那么对于proposal_1(n1, v1), n1>n, 那么有Acceptor接受proposal_1, 必然有

   v1==v. 这也是显而易见的, 因为如果v1 != v, 那v1将会chosen, 这就违反了v一旦chosen就不能改变的限制

   也就是说, chosen是由accept决定的, 所以chosen唯一推理除accept也唯一, 即使proposal number不断增大, 但是accept的值都是chosen的值


3. P2b. If a proposal with value v is chosen, then every higher-numbered proposal issued by any proposer has value v.

   因为Acceptor不知大哪个值被chosen了, 它们只是接受所有大于自己pn的请求. 所以我们必须要求Proposer, 一旦Proposer发现某个值v是chosen了

   那么Proposer必须选择该chosen值v作为写入的值. 这也是显而易见的, 如果Proposer知道proposal(n, v)已经被大多数Acceptor接受了, 但是仍然选择propsal(n1, v1) n1>n

   向Acceptor发起写入请求, 那么显然chosen值就从v修改为v1. 因为Acceptor判断n1大于自己的pn=n, 所以都会接受proposal(n1, v1), 所以v1就被chosen了

   如果Proposer选择proposal(n1, v)发起写入请求, 那么即使proposal number一直增加, 但是chosen值一直没变

4. P2b如何能满足P2呢?


   假设值v在pn=i的是chosen了, 同时我们假设proposal number=m, i< m < n, 的写入请求, 其值都是v, 也就是写入的proposal为proposal(m, v), i < m < n

   所以对于所有i<m<n的写入, 总是有大多数Acceptor接受了, 又由于大多数集合总是至少又一个元素重合, 所以对于当前proposal(n), 这个时候值没有决定, 这个只是prepare阶段

   我们得到大多数集合返回给我们它们接受的值, 则又{(i, v), (i+1, v), ..., (m, v)}, 显然如果我们选择pn最大的值作为写入值, 也就是值v, 那么就能保证P2, 也就是

   我们在pn=n下, chosen的值依然是v, 保证了v不能被改变的限制


5. 举个例子, 为什么选择序号最大的呢?

   如果一个值被chosen了, 那么必然大多数accept了该值, 那么下一次发起prepare的时候总是能看到该值的, 因为prepare必须至少大多数Acceptor返回成功

   也就是我们有proposal(10, a)被chosen了, 我们至少有任意3个Acceptor接受了该proposal, 假设我们的集合为A1(10, 10, a), A2(10, 10, a), A3(10, 10, a), A4和A5的pn依然是0

   那么对于P2, 发起Prepare(15)的时候, 任意一个大多数集合{A1, A2, A3}, {A1, A2, A4}, {A1, A2, A5}, ....等等, 至少包含A1, A2, A3中的一个

   显然我们选择proposal number最大的值作为写入值, 也就是a, 必然能保证不会修改a这个chosen值


6. 什么情况下出现Prepare返回有不同的proposal number和value呢？

   那必然因为某些写入失败了. 比如对于Proposal(10, a), 只被A1, A2接受了, 那么有{A1(10, 10, a), A2(10, 10, a)}, 显然此时a不算chosen

   对于Prepare(11), 只有A3, A4, A5收到了, 显然此时我们可以选择任何值, 假设我们选择b, 我们写入Proposal(11,b)

   假设只有A3, A4接收到了Proposal(11, b), 那么我们有{A3(11, 11, b), A4(11, 11, b)}. 

   同时我们注意到a不可能被chosen了! 为什么, 因为A3的pn变为了11, 那么Proposal(10,a)到达A3的时候, 必然被拒绝的. 

   然后继续, 对于Prepare(13), 我们收到至少大多数Acceptor返回, 假设我们得打A1, A2, A3, A4的返回, 我们发现

   pn=11, 接收了a, pn=12接收了b, 那该选哪个呢?

   显然选pn=12嘛, 因为pn=12会使得pn=11必然失败!!!!!!

   **那这里pn=11和pn=12都是2个Acceptor, 打平了, 为什么不是任意选一个值, 或者选择我们自己的值k呢?**

   因为我们不知道A5的结果呀, 但是如果A5收到了任何写入请求, 其成功的Proposal必然是Proposal(11, b), 必然不是Propsal(10, a). 要么Proposal(10, a)被Proposal(11, b)覆盖

   要么Proposal(11, b)使得A5拒绝了Proposal(10, a)!!!!!!!!!!!!! 就算A5也向我们返回了其结果, 其结果也必然要么是Propsal(11, b), 要么没有收到任何Prepare, 其proposal number依然是初始值0(或者-inf)

   所以即使我们没有收到所有的Acceptor请求, 但是可以根据大多数返回结果来推理出结果

7. 所以说, 我们要么可以选择任何值, 也就是Prepare返回我们发现没有任何Acceptor接收了任何值, 要么我们必须选择pn最大的值, 也就是最新的值作为我们写入的值

   因为既然出现更大的pn, 那么表示所有较小的pn都会失败, 为什么更大的pn能写入不同的值呢? 那必然是较小的pn的写入并没有被至少大多数节点接受, 所以不算chosen, 所以我们可以写入任何值


Basic Paxos正确性的反证法证明
===============================


根据参考4

如果在P, Q两个时间点, 或者更准确的说, 如果对于两个Proposal number, P和Q, 其中Q > P, 如果P和Q分别chosen了一个值vp, vq, 有没有可能vp != vq

如果不相等, 那么在P和Q之间的某个Proposal number=R, 其chosen的值是第一个chosen值不等于vp的值.

也就是说对于所有Proposal m, P <= m < R, chosen的值都是vp, 那么如果在R, 我们发起Prepare的时候, 得到至少大多数Acceptor返回, 这里这些Acceptor表示为集合S

而某个acceptor A是属于S中, 同时A也属如所有m的集合中, 也就是说A是所有大多数集合的重合. 所以A其最大proposal number为R-1, 同时值必然是vp. 因为所有Proposal number大于等于p, 小于R的

Acceptor都接收了值vp, 所以A必然也接收了vp

如果R从A得到一个不等于vp的值, 显然和A的性质相悖






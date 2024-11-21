

# Paxos

1. https://www.youtube.com/watch?v=JEpsBg0AO6o
   https://ongardie.net/static/raft/userstudy/paxos.pptx

2. https://davecturner.github.io/2016/09/18/synod-safety.html

3. https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-935.pdf

4. https://raft.github.io

5. https://fpaxos.github.io

6. https://lamport.azurewebsites.net/pubs/web-dsn-submission.pdf

here we are going to talk about some engineering details for implementing the Synod protocol and a state machine that performs
minimum functionalities.

# the Synod protocol

let's cut to the chase and take a look at when a value can be considered as chosen.

> The value is chosen when a large enough set of acceptors have accepted it. How large is large enough?
To ensure that only a single value is chosen, we can let a large enough set consist of any majority of the agents.
> 
> -- Paxos Made Simple

the necessary and sufficient condition for a value becoming chosen is simple and straightfoward, which is that a value has
accepted by a majority of acceptors.

the safety of the Synod algorithm can be proved by a proof of contradiction given in the paper `The Part-Time Parliament`.

basically you can think of sucn a scenario where a value has been accepted by a majority of acceptor, and subsequently, any
proposer will see that value because any two majorities would have at least one acceptor in common.

so if we take the value assigned with the largest ballot number, then the value must be the one that the proposer sends in the
phrase 2, leading to a fact that the chosen value will be preserved consequently.

that is more of an informal and shortcut intuitive grasp of the proof, and the reference 2 offers an illustrated presentation of
that proof, and it really simplies that proof of contradiction in the original paper and gives you an easily-understanding and
clear description.

and when dealing with implementation ins and outs, there are some edge cases that probably are not laid out well enough in either
of the simple paper and the original paper.

to get a complete picture of the algorithm, you have to read basically every single word carefully.  

## the proposer's algorithm for the unchosen values

the question is what about the values that were not chosen?

suppose that there were three acceptors called A1, A2 and A3, and three proposer P1, P2 and P3, and you might encounter such a
case where P1 proposed a proposal with a ballot number of B1, and let's assume that all acceptors promised to this proposal.

and next P1 sent an accept request with a value of V1 to all three acceptors, and the only one acceptor that replied was A1, in
this case, V1 was not chosen.

and later, P2 asked a promise from all three acceptors by sending a proposal associated with a ballot number of B2, where B2 > B1.

but due to networking problems, though A1 was unable to get that proposal from P2, A2 and A3 could still form a valid quorum,
which contains a majority of the acceptors.

so P2 would continue and send an accept request with a value of P2 to A2 and A3, but again some kind of malfunction of mahcine
occured leading to that A2 received that accept request, wrote that value into its storage and replied a yes back to P2 , whereas
A3 had just got nothing.

so far, all there acceptors would be like

```
     max-promised-ballot-number     max-accepted-ballot-number  max-accepted-value
A1         B1                                    B1                V1
A2         B2                                    B2                V2
A3         B2

```

and then it was P3's turn to run the algorithm for writing a value of V3, and luckily, P3 has good connections with all the
acceptors, and it started by sending a proposal of B3 to all the acceptors, and it got response from all of them.

and then P3 would know that there are two candidates, V1 and V2 along with that A3 had promised a ballot number of B2, but
A3 had not accepted anything, meaning that the proposal of B2 had failed, and V2 was not a chosen value, meaning no one
had been chosen.

and then the question is can we propose whatever value we want?

no, according to the safety requirements for consensus:

> • Only a value that has been proposed may be chosen,  
> • Only a single value is chosen, and  
> • A process never learns that a value has been chosen unless it actually has been.
> 
> -- Paxos Made Simple

the first one implies that if you ever see any value that was being proposed before, the value you will be proposing must be one
of them, you can not write the value you wanted. 

and the candidate must be the value of the highest-numbered proposal among all proposals numbered less than your ballot number.

in our case, we would rule out A3 since it had not accepted any value, and the value with heighest ballot number was going to be
V2, then P3 would try to write V2 and replicate it to the acceptors.

but you might be seeing no candidate in some cases where you can basically write any value you want, how?

in the case above, suppose that P2 lost its connection to A1, but it still had A2 and A3 in touch, and both A2 and A3 had not
accepted any value, then no candidate detected, and then P2 was free to write any value.

```
                          max-promised-ballot-number     max-accepted-ballot-number  max-accepted-value
                     A1         B1                                    B1                V1
    P2  -------->    A2         
        -------->    A3         

```

and here is another case that remains unclear to readers.

yes what we are doing is basically trying to enumerate every possible edge case for the algorithm, which is impossible and
bad for the proof, but luckily there are just few cases that we have to come across here.

the example would be that P2 could talk to A1, and at phase one, obviously P2 knew that V1 must be the candidate, and then it
would try to write V1 to all the acceptors.

but unfortunately, P2 suddenly lost its connection to A3 and A1, and we ended up with that only A2 accepted and saved the value
of V1 this time.

```
     max-promised-ballot-number     max-accepted-ballot-number  max-accepted-value
A1         B2                                    B1                V1
A2         B2                                    B2                V1
A3         B2

```

if now a leaner started to learn the chosen value, would V1 being considered as chosen? 

even though it was clearly accepted by a majority of acceptors, the short answer is no, V1 was not chosen yet, why?

we once wrote an email to lamport to try to get a full explanation, and lamport did reply and said:

> If you are confused, please read the original paper that contains the unambiguous mathematical description of the algorithm.

so let's go revisit the orginal paper.

## the learner's algorithm

to explain why V1 was not considered chosen, the best thing to do is to re-perform the process how priests reach an agreement
on one single decision described in the manuscript in Figure 1 of the orginal paper.

```

here a priest voting for a proposal is represented by an exclamation next to it.

#   decree     quorum and voters!
2     α         A  B    Γ    ∆!
5     β         A  B    Γ!       E
14    α            B!        ∆   E!
27    β         A!      Γ!   ∆!
29    β            B!   Γ    ∆
```

let's focus on the ballot No.14 and No.27, and according to the papaer, ballot No.27 is successful and No.14 is unsuccessful.

actually lamport does not clearly say that the ballot No.14 is unsuccessful, but given the context, it is logical to take 14 as
unsuccessful.

as we can see, the priest `∆` votes proposal `α` at the ballot No.2, which is the eariest ballot, and in the ballot No.14, `∆` is
the only one who already votes for a ballot, so the decree for ballot No.14 is going to be `α`.

but the priest `∆` does not vote in the ballot No.14, leading to that the chosen decree is not determined yet at ballot No.14!

you might have such an illusion that the decree `α` seems to be accepted by a quorum, actually not all the priests in one quorum
cast their votes at ballot No.14.

we will see the difference in comparison to the ballot No.27.

in the ballot No.27, we have two priests in the quorum that have already voted for a decree, the priest `Γ` votes for the decree `β`
at the ballot No.5, and the priest `∆` votes for the decree at the ballot No.2.

what's important to keep in mind here is that the priest `∆` does not vote at ballot No.14, so the largest voted ballot number for
`∆` is going to be 2.

and then the decree for ballot No.27 must be one with the largest ballot number among the decrees that the priests in the quorum
have voted.

and we have two candidate, the decree `α` that `∆` votes for at the ballot No.2, and the decree `β` that `Γ` votes for at the ballot No5.

and apparently the decree for the ballot No.27 is going to be `β`, and this time all the priests in the quorum votes for the decree!

according to the protocol, there is at least a quorum of priests agrees on a decree, then the decree will be considered as chosen and
written into their ledges with indelible ink, and the fact can not be reverted.

one thing we noticed that differs in between the ballot No.14 and the ballot No.27 is that the number of priests who cast votes.

at the ballot No.14, only two priests cast their vote meaning less a majority of priests would commit the decree `α` to paper, and
at the ballot No.27 we have at least a majority of priests agree with the decree `β`.

we can conclude that a value is chosen if and only if all the acceptors accept the value with the same ballot number, or the
two-phrase algorithm runs successfully for the value, both the phase 1 and the phase 2 must be successfully executed for the value.

the ballot No.14 shows that even there is a majority of acceptors that have written the value into their storage, but with
different ballot number, we still can not say that the value has been chosen.

## the acceptor's algorithm

the acceptor's algorithm is quite simple. 

an acceptor must reject a proposal with a smaller ballot number and any acceptence with a smaller ballot number.

more precisely, an acceptor will only promise a proposal with a larger ballot number than the heighest numbered ballot it has promised.

and it must only accept an acceptence if and only if the ballot number is equal to its maximum promised ballot number, and greater
than maximum accepted ballot number it has accepted.

## disjoint ballot number sequences

someone offers a theoretical proof for generating infinite disjoint sets
on [stackoverflow.](https://math.stackexchange.com/questions/51096/partition-of-n-into-infinite-number-of-infinite-disjoint-sets)

but here we prefer a third dedicated standalone service that is responsible for allocating and dispatching ballot numbers used
by proposers.

## examples

you can run the function `synod_pannel.no_candidate_detected` to see what will happen in the case where none of candidate detected.

the log will show you how the acceptors, proposers and the learner work at any point of time.

# implementating a state machine 

we will borrow some ideas from Raft, which is an invariant of MultiPaxos protocol.

here we assume that the set of servers or nodes is fixed and no support for reconfiguration.

and one of the most important observations about MultiPaxos is going to be any two qourums must be intersected.

but this requirement can be weakened further under particular conditions.

> A leader can send its "1a" and "2a" messages just to a quorum of acceptors. As long as all acceptors in that quorum are
working and can communicate with the leader and the learners, there is no need for acceptors not in the quorum to do anything.
> 
> -- Cheap Paxos

> Paxos uses majority quorums of acceptors for both Q1 and Q2. By requiring that quorums contain at least a majority of acceptors
we can guarantee that there will be at least one acceptor in common between any two quorums. Paxos's proof of safety and
progress is built upon this assumption that all quorums intersect.
> 
> -- Flexible Paxos(FPaxos)

why?

an informal and short answer is going to be if any new leader-elect can learn the history of the log entries from somewhere, then
it is free to write values to any quorum it likes.

this acts as the foundation for our state machine implementation. 

## leader election

leader election is a must for the efficiency of MultiPaxos, not a necessity for its safety.

> However, safety is ensured regardless of the success or failure of the election.
> Election of a single leader is needed only to ensure progress.
> Key to the efficiency of this approach is that, in the Paxos consensus algorithm, the value to be proposed is not chosen until 
phase 2.
> 
> -- Paxos Made Simple

leader selection requires to be partition tolerant, and it is, compared to consensus itself, a trivial problem to solve.

those factors comebined is probably we guess the reason why leader selection is left out in the paper.

so to speak, leader election is separate from MultiPaxos, you can use any algorithm you want. 

there are more robust and sensible methods out there that are designed particularly for leader selection, for instance, `Leases`.

here we are going to go with a similar approach employed by Raft, but a relatively simplified version.

and it works as follows:

if leader fails, any node would start a new election term to try to grab the leadership.

a server is going to vote for one candidate including itself only in one election term, and if no one claims leadership in a
certain period of time, then start another round or term of election.

we are using randomized timers in hope of a new leader being elected as quickly as possible.

the drawback of this approache is that servers might enter a live lock where no leader would be elected.

> However, without extra measures split votes could repeat indefinitely.
> 
> -- Raft

here we make some little adjustments to the original approach.

that is that a server would only cast one vote in one term, and in Raft, a server will abandon its election proposal if
it receives an election proposal from another server while waiting for response to its election proposal.

here instead of a kind of relatively humble behavior, we rather a more selfish mindset where a server rejects any other electiion
proposal if it has voted for a candidate inclduing itself in one term.

e.g. we have 3 servers, A, B and C, and A has not received any election proposal, so it deicdes to vote for itself and send an
election proposal to others, and B votes for itself too, and will reject the election proposal from A.

suppose C hasn't cast its vote for anyone including itself, then which one, A or B, takes the leadership will be determined by
which election proposal arrives at C first.

```
    A(A)      B(B)
    
         C()
```

if C gets a proposal from A first and rejects B's, then A will become the leader, and vice versa.

## partitions

leader election should be a rare event in the whole life cycle of the system, and would only be triggered by particular conditions

in general, it's when the leader fails and becomes unreachable to all the other servers, the rest of servers will start a new round of
election.

for instance, the system partitions into multiple subnets of network where each of them is unable to connect with the others.

but only the one that contains a marjority of servers will lanuch leader election to try to recover from this failure.

put simply, a new leader will be elected once there are partitions, and synchronization through heartbeat messages is a commobly
used method for partition detection.

let's take a look at some examples.

suppose we have 3 servers in the system, and they are denoted by A, B and C.

case one, C is the leader, and both A and B lose their connection to C, then a new leader will be elected from A and B. 
 
```
A        B

   C(X) 
```

case two, we have 5 servers, A, B, C, D, E, and A is the leader and A and B form a subset, and C, D, and E form another subset,
and these two subsets are totally disconnected.

obviously A and B together can not form a working system since there are only two servers less than a majority of servers.

and C, D and E, they notice that no one in the partition can connect to the leader, and it is time to elect a new leader
to counteract leader failure.

```
+-------+      +---------+
| A   B |      | C  D  E |
+-------+      +---------+

```

and there is a case in which election is probably undesirable.

that is that some servers have no connection to the leader, but at the mean time the leader still has at least half of the servers
includede in the partition.

the leader is still working, and it can accept and write values from clients.

```
+-------+      +---------+
| A   B  <--->  D   E    |
|   C   |      +---------+  
+-------+      

```

in the above diagram, D and E have connection to server B but no connection to A and C.

and D and E find that no leader detected and there are at least half of the servers they can get in touch with, then they might
decide to elect a new leader.

but in this case, the whole system is still regarded as running and working, and leader electin will cause a live lock where
servers in either subset will try to grab the leadership over and over again leading to no server can actually become in charge.

one possible solution is that any server losing its connection to the leader would not start election unless:

1. there are at least a majority of servers that it can talk to.

2. no one in the partition can talk to the leader, or the leader is not working.

in the previous case, A, the leader, is still running, and it periodically sends heartbeat messages to all other servers in order to
synchronize its working state to others.

and any server would mark the leader as online once it receives a heartbeat message from the leader.

and when D and E have not received heartbeat messages from the leader over a particular timeout, they will first ask others for
the working state of the leader.

and B will send the leader information back to them to tell them that do not worry, the leader is still running and working, then D
and E will cancel their election process, and nothing to do.

if B loses its connection to the leader as well, then B, D, E form a majority subset, in this circumstance, an elecetion would be
initiated by B, D and E.

but what if the connection between D and B and the connection between E and B are unblocked, but A loses connection to C but retains
connection to B?

```
+-------+      +---------+
| A   B  <--->  D   E    |
+-------+      +---------+ 

    C       

```

B is still getting heartbeat messages from A, and the fact that the leader is still running will be synced with D and E, but
actually the system is not working because there are less a majority of the servers that are connected with each other in the
partition where the leader A lives.

the leader A will notify others through heartbeat messages that the system is not working when it can not receive response from
at least half of the servers.

in this case, B, D and E would make their decision to take over the system by starting election.

## defer history recovery

MultiPaxos supports batching and pipelining requests for higher throughput and lower latency by allowing to write the value to the
next position at i+1 index before the current ith position becomes chosen.

and the safety of Paxos requires that the new leader must learn all the history log entries.

so when a new leader is elected, it will first try to fill in the log array with all the entries written by the former leader.

once this history recovery process has done, it's safe for the new leader to write values from clients.

here we postpone learning history log at phase one, and when a new leader is elected, it can immediately proceed to handle write
requests from clients and populate the log array without conflicts on indices.

how? we maintian two pointers called left-idx and right-idx.

we conceptually divide the log array into two subarray, the left contiguous chosen subarray, and the right gap subarry.

in the left contiguous subarry, every position is chosen wherease some positions remain unchosen leads to gaps in the right subarray.

```
here a symbol C indicates that the value for a position is chosen, X for unchosen.

i = left-idx
j = right-idx

0, 1, 2, ...., i, i+1, ..., i+ N, j 
C  C  C        C   X         X    C

```

the left-idx is the last index in the left subarray, and the right-idx is the largest index that the leader has ever been
trying to write to.

when a server receives an election proposal from other server, it will reply with its left-idx and right-idx.

and then the new leader knows the range of the log array that it should recover by a calculation on the left-idx and right-idx
received.

suppose there are 3 followers, F1, F2 and F3, and their left-dix and right-idx as follows:

```
     lef-idx     right-idx  
F1      5            20
F2      8            10
F3      3            12

the log array

0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, ...
               F1                                                     F1
                        F2    F2
         F3                           F3
```

apparently, the leftmost index of the range is going to be the minimum of those three left-idx indices, and plus one, which is 4.

and the rightmost is going to be the maximum of the right-idx indices, which is 20.

so when a server becomes the new leader, it will increase its right-idx by one, which will be 21 in this case.

and instead start synchronizing the history log entries, the new leader will just finish and terminate the phase one, and become
ready to write any value.

it is totally fine because the next value will be placed into the index 21.

but there are still log entries to be recovered, so before transitioning to write-ready state, the new leader will spawn a background
task to do the recovery.

the new leader asks followers to report their log entries on those consecutive indices from the leftmost to the rightmost.

and note that the leftmost is the sum of the minimum left-idx plus one, why?

because the value at the index 3 is already chosen, and it can not be changed, and this implies that all the followers will have
the same chosen value at the index 3.

for F3, it has no idea what should be placed in the position at the index 4, because index 4 is unchosen to it, but F1 and F2 have
a chosen value at index 4.

and actually the chosen values at the indices from 4 to 8 are already determined becase F2 have all the chosen value inside, and no
one can rub them out from the position.

but as for the values at the indices from 9 to 20, we must run Paxos for each position to determine the chosen values.

by introducing this method, you might have data lost if the leader crashes before it competes history recovery.

it should be acceptable because this type of data lost perfectly accords with what happens in the manuscript mentioned in Paxos.


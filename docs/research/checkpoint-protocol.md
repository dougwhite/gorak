# Compact checkpoint protocol: requirements and decision gates

Status: design requirements, not an implemented protocol. The first live
experiments rejected naive global and source-partitioned revision rows; see
[revision-token acceptance](revision-token-acceptance.md). The current diagnostic
retains exact event receipts, full-history observations and a full-export oracle.
The next implementation must replace those costs without weakening their guarantees.

## Required meaning

A checkpoint must identify the source database generation, consumer, verified
source snapshot and a closed set of committed changes. It must distinguish an
empty pending set from a gap in retained history. A monotonically allocated event
ID is not a commit position: an older transaction may commit after a newer one.

The current multi-chunk reader deliberately uses one pending-event query and no
intermediate acknowledgment. It solves collection across fetch boundaries only.
Its before/after count check is still a diagnostic, and receipt membership still
costs work proportional to retained history.

## Contracts to establish before choosing a schema

1. **Transactional capture.** Source mutation and captured invalidation must commit
   or roll back together. Test failed capture, deadlocks, disconnected writers and
   multi-statement Workbench operations. An operation may span several transactions;
   do not describe such an operation as atomic without evidence.
2. **Closed observation.** A reusable source snapshot needs a validation token that
   changes when any relevant committed mutation becomes visible. Test a writer
   that starts before observation and commits during or after it, including lower
   allocated event IDs. If validation fails, discard staged progress and retry.
3. **Checkpoint publication.** Publish local source evidence before making new
   progress eligible for server acknowledgment. Retries after uncertain server
   commits must be idempotent. Restoring an older checkout must not silently adopt
   newer server progress.
4. **Generation and restore.** Database-resident tokens alone cannot distinguish a
   physical restore that restores those same tokens. Define an explicit DBA restore
   generation-change procedure, or an independently persisted authority, and test
   it. A documented operator contract is acceptable; claiming automatic detection
   without that authority is not.
5. **Retention.** Pruning needs a supported consumer lifetime and a retained-history
   boundary. A consumer behind that boundary must rebootstrap, never infer that an
   empty query means no changes. Abandoned consumers must not retain history forever.
6. **Bounded cost.** A quiet check must avoid whole-history scans, source payload
   downloads and per-event receipt transfer. Measure writer overhead as well as
   reader latency. Bound memory, lock duration and reconnect work explicitly.

## Initial candidate and experimental decision

The initial experiment prototyped a transactionally updated database revision alongside existing event
capture in a disposable database. Its purpose is to test a cheap committed-change
validation token, not to replace event identity or act as a sequence watermark.
A global row is the simplest candidate to reason about, but may serialize writers
for their entire transaction. Long transactions and concurrent writers are therefore
acceptance gates, not later tuning. Do not deploy it to ordinary source databases
until those effects are measured.

If that cost is unacceptable, evaluate partitioned revisions or a separate sealing
protocol. Those alternatives need proofs/tests for transactions touching multiple
partitions, lock ordering, concurrent observation and late commits. Do not assume
that adding shards preserves correctness or removes contention.

Keep event enumeration and source validation separate: a revision token can detect
change without providing the identities needed to refresh affected applications.
Receipt compaction and pruning need their own transition protocol; neither follows
merely from adding a revision counter.

The isolated experiments confirmed global contention and an opposite-order
partition deadlock on disjoint source rows. The next investigation is writer-specific
lanes with stable assignment throughout a transaction. Identity, restart/reuse,
initialization and compaction must be established before adopting that design.
Neither initial candidate was installed into ordinary tracking.

[Writer-session experiments](session-revision-acceptance.md) subsequently passed
independent writes, rollback and reused-identity checks under MVCC. However,
page-locking writers still contend and online lane deletion can reject a writer
with SQLSTATE 40001. The next gate is the actual writer lock configuration contract.
Retained counters with a bounded reader/fallback are preferable to unproven online
cleanup for an initial implementation; storage maintenance remains explicit.

## Next acceptance sequence

- Completed initial primary-documentation review and isolated multi-connection
  experiments; preserve the observed contention/deadlock results.
- Completed initial global revision rollback, held-writer, concurrent writer and
  reader checks, plus a source-partitioned reverse-commit/deadlock experiment.
- Initial writer-specific identity/reuse and lifecycle races are tested; validate
  writer lock settings, cross-user rule execution and restart behavior before schema
  integration. Do not deploy automatic deletion of retained counters.
- Specify the checkpoint state machine and failure transitions from those results.
- Test local publication failure, server commit uncertainty, restored local state,
  changed database generation, expiry and pruning before integrating source reads.
- Compare selective results to full exports throughout live acceptance.
- Enable normal status only after continuity and invalidation are certified; add
  push conflict-check integration afterward.

This work does not require another manual Workbench action for the initial protocol
experiments. Cross-application moves, version restoration/purge and physical restore
acceptance remain separate coverage gates before broader claims.


### Writer configuration progress

[Owner-rule and actual OpenROAD CLI experiments](writer-configuration-acceptance.md)
confirmed caller identity/permissions and process-local row-lock initialization at
import/compile source mutations. Active Workbench settings, table-specific startup
integration, multi-server/restart identity and bounded observation remain gates.
No global defaults, installed tracking or normal source-command behavior changed.


The [counter-reader matrix](counter-reader-acceptance.md) subsequently showed that
serializable ROW writers exclude MVCC readers. The counter-table contract must
therefore use MVCC/shared on both sides, preserving application isolation and
source-table settings. CLI and controlled manual Workbench MVCC writer/reader acceptance passed.
General initialization, bounded observation and identity/retention work remain.

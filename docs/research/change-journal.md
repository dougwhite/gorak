# Transactional change journal prototype

Research checkpoint: 2026-09-13. This validates transaction mechanics on disposable
user tables in an isolated Ingres 12 database. It is not `gorak install`, does not
install rules on OpenROAD catalogs, and does not establish complete source coverage.

## Prototype

Three tables represent source rows, events, and consumer acknowledgments. An Ingres
sequence allocates event identities. AFTER INSERT/UPDATE/DELETE rules call one
procedure that inserts the affected object identity and operation into the journal.
Deletes use the old identity. The prototype source identity is immutable; real rules
must account for both identities when a key or parent relationship changes.

A rule-generated insert participates in its caller's transaction. The probe verified
that rolling back the source write also removes the event. Sequence gaps are normal
and must not be interpreted as missing committed source writes.

The prototype used 8 KB tables with explicitly selected B-tree storage. An initial
writer test scanned the journal before committing and blocked the second writer.
Changing heap to B-tree alone did not fix it. Reading the sequence's session-local
current value instead of scanning the journal removed that artificial dependency.
This is evidence to keep rule/writer work narrow, not a broad contention benchmark.

## Verified cases

| Case | Observed result |
|---|---|
| Source insert and rollback | Source event was rolled back |
| Writer A allocates 2, writer B allocates 3 and commits first | B committed while A remained open |
| Ordinary row-locking reader scans during A | Reader hit the configured lock timeout |
| MVCC reader scans during A | Saw committed event 3, not uncommitted event 2 |
| A subsequently commits; consumer already acknowledged 3 | Event 2 remained discoverable |
| Second consumer has no acknowledgments | Both committed events remained visible |
| Source update | Update event captured |
| Source delete | Tombstone event remained after source deletion |

These checks exercised actual ODBC sessions and actual database rules. No original
application source was modified. Synthetic prototype tables are separate from
OpenROAD source tables. The successful MVCC prototype is retained in the isolated
acceptance database; machine-specific names and raw scripts remain outside Git.

## Cursor implications

`WHERE event_id > last_seen` is incorrect: allocation order is not commit order.
The verified primitive instead selects committed events not explicitly acknowledged
by that consumer, using an anti-join on `(consumer_id, event_id)`. The pending lower
ID remains discoverable after a higher ID has been acknowledged.

This is a correctness primitive, not the final scalable query. Acknowledgments and
retained events can grow without bound. Before production:

- Define consumer registration and initial snapshot bootstrap without a race.
- Write local verified baselines durably before acknowledging their observed events.
  A crash between the two should replay work, not lose it. Do not acknowledge later
  events for an object merely because an earlier event for that object was processed.
- Batch acknowledgments and deduplicate candidate objects for expensive fetch/hash
  work, preserving event identities for correctness.
- Specify retention across active/offline consumers. Expiring a consumer or pruning
  needed history must force that checkout to rebootstrap using a generation token.
- Prove event pruning does not skip transactions still in flight. Do not turn the
  highest acknowledged number into an implicit garbage-collection watermark.
- Measure empty and large-backlog queries, indexes, log growth, rule overhead, and
  concurrent bulk saves before selecting the final storage layout.

## Reader protocol

MVCC worked in the inspected isolated database and exposed only committed events
without waiting for an unrelated writer. Use explicit read locking/isolation choices
and finish reader transactions promptly so later polls get a fresh snapshot.
Do not use READLOCK=NOLOCK as a performance shortcut: it bypasses MVCC semantics.

The installer/check command must verify MVCC and required table/storage capabilities.
Do not silently change server-wide settings or assume every supported installation
has identical capabilities. Ordinary locking remains safe if failures stop progress,
but may not meet the interactive latency target during active writes.

## Next acceptance slice

1. Design installer metadata: schema version, installation/database generation,
   ownership/privileges, and expected rule/procedure definitions.
2. Probe real source-table coverage in a disposable application database: chunks,
   app metadata/includes, keys/versions, referenced storage, compilation and deletion.
3. Demonstrate a rule failure rolls back the originating source operation and decide
   how installation health is checked before allowing the fast path.
4. Benchmark large chunk saves and backlog retention; consider statement-level
   capture or other deduplication only after correctness is established.
5. Build bootstrap, polling, durable acknowledgment, and recovery as shared services;
   expose installation only after those gates are reproducible.

## Primary references

- [Ingres CREATE RULE](https://docs.actian.com/ingres/12.0/SQLRef/CREATE_RULE.htm):
  rule ownership, procedure execution, and row/statement scope.
- [MVCC](https://docs.actian.com/ingres/12.0/Upgrade/Multiversion_Concurrency_Control_%28MVCC%29.htm):
  committed snapshots and optional session-level activation.
- [MVCC and read locks](https://docs.actian.com/ingres/10S/DatabaseAdmin/Lock_Level_MVCC_and_Readlock.htm):
  READLOCK=NOLOCK overrides the MVCC locking behavior.

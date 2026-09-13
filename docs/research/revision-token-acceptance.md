# Revision-token and multi-chunk live acceptance

Date: 2026-09-14. Isolated Ingres database, direct ODBC, disposable ordinary
user-owned tables and rules. No OpenROAD source tables or installed capture hooks
were changed. All scratch rules, procedures and tables were removed.

## Multi-chunk pending window

The production journal reader returned all 704 retained events using fetch sizes
of seven and three. Both reads exhausted the pending query and returned the same
set of unique event identities. A budget of 14 returned 14 events and inspected
one additional event, correctly reporting an incomplete window. The observer was
fresh and no events were acknowledged. Before/after journal observations matched.

The three polls together took approximately 73 ms in this isolated run. This is
not a status-command benchmark: it excludes XML exports, full source comparison,
large receipt histories and production-sized event tables.

## Global revision candidate

The scratch source table had an integer primary key and a payload. A second table
held one bigint revision row. Both tables used BTree storage and 8192-byte pages.
Insert, update and delete rules called a procedure whose body was:

```sql
update revision_probe set revision = revision + 1 where id = 1;
```

Independent ODBC sessions used MVCC, shared reads and a two-second lock timeout.
The tests checked committed values using fresh reader transactions.

Observed:

- An uncommitted source insertion did not change the reader's revision. Rolling
  back removed both source and revision changes.
- Committed insertion advanced the revision. Multiple source mutations in one
  transaction became visible together when committed.
- A revision constraint deliberately rejected capture; the source update did not
  persist after rollback. This establishes the tested SQL behavior, not atomicity
  for every multi-transaction Workbench operation.
- While one writer held the revision row, a second writer inserting a different
  source object timed out after approximately 2.011 seconds (SQLSTATE 5000P).
- After releasing the first transaction, the second writer committed in 2.283 ms.
- With the revision rules removed, the same independent-source writer committed
  in 1.923 ms while the first source writer was still uncommitted. This control
  isolates the extra contention introduced by the revision rule.

One complete run measured:

| Operation | Samples | Median | Maximum |
| --- | ---: | ---: | ---: |
| Warm revision read plus reader commit | 50 | 0.355 ms | 0.466 ms |
| Uncontended source update plus commit, revision rule enabled | 25 | 2.128 ms | 3.581 ms |
| Control update plus commit, revision rules removed | 25 | 2.202 ms | 3.375 ms |

The small sequential samples do not establish relative throughput or overhead;
cache/order effects and network variation were not controlled. A read while a
writer was pending completed in 0.771 ms and saw the prior committed revision.

**Decision:** do not adopt one global revision row. Its cheap reads are attractive,
but holding it for the source transaction introduces contention between otherwise
independent writers. Longer transaction durations would extend that contention.

## Two revision partitions

A second experiment used two revision rows and an insert rule selecting a row
from the inserted source object's slot. Different source objects were used for
every mutation, so source-row overlap could not cause the test conflict.

A writer using the second slot committed in 2.536 ms while the first-slot writer
remained uncommitted. A single query saw the vector `(0, 1)`, then `(1, 1)` after
the first writer committed. This demonstrates the tested reverse-commit case.

Next, transaction A wrote slot 1 and transaction B wrote slot 2. Each then inserted
another distinct source object using the opposite slot. Ingres rejected one
transaction with SQLSTATE 40001 after approximately 0.498 seconds; the other
committed. Both source rows and revision increments of the victim were rolled
back. This was a revision-lock cycle on otherwise disjoint source rows.

**Decision:** merely partitioning revisions by source object/application is
insufficient. Workbench controls mutation order, so Gorak cannot assume all source
transactions acquire these added locks in a common order. Do not deploy this
candidate without a different protocol.

## What this establishes and what remains

These experiments validate rollback and committed visibility for two small SQL
prototypes, and reject their naive writer-locking designs. They do not certify a
checkpoint protocol, restore detection, pruning, source invalidation coverage or
fast status. Installed tracking remains unchanged.

The next candidate to investigate is a stable writer-specific revision lane:
every mutation from one writer uses its own lane throughout a transaction. First
establish session identity semantics, lane lifetime, server restart/reuse behavior,
concurrent initialization and safe bounded compaction. Do not assume a session ID
alone is globally unique or durable. Reading an ever-growing table of retired
sessions would just replace one history scan with another.

A lane token still does not enumerate changed objects or acknowledge them. The
source-validation token, event-retention boundary and consumer checkpoint remain
separate parts of the eventual protocol.

## Primary references

Actian documents that MVCC writers hold exclusive locks on updated rows; this
explains why shared revision updates can contend despite nonblocking readers.
See [Lock Levels](https://docs.actian.com/actianx/12.0/DatabaseAdmin/Lock_Levels.htm)
and [LOCKMODE](https://docs.actian.com/ingres/12.0/SQLRef/LOCKMODE.htm).

Snapshot timing depends on isolation level; see
[Multiversion Concurrency Control](https://docs.actian.com/ingres/12.0/Upgrade/Multiversion_Concurrency_Control_%28MVCC%29.htm).
Session/server information is available through
[DBMSINFO](https://docs.actian.com/actianx/12.0/SQLRef/DBMSINFO_Function.htm),
but those documented identifiers alone do not establish a lane lifecycle protocol.

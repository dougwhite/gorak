# Counter reader compatibility acceptance

Date: 2026-09-14. Follow-up to the reader timeout during the configured Workbench
save in [writer configuration acceptance](writer-configuration-acceptance.md).

## Cause and controlled reproduction

Actian explicitly documents that serializable ROW-locking transactions are
incompatible with MVCC access to the same table: they acquire a table MVCC
compatibility lock that excludes MVCC transactions because they may internally
switch to PAGE locking to prevent phantoms. See
[Table Lock Level Compatibility](https://docs.actian.com/actianx/12.0/DatabaseAdmin/Table_Lock_Level_Compatibility_in_an_MVCC-capabl.htm).

An isolated live matrix reproduced that distinction without Workbench or source
rules. A BTree scratch table with 8192-byte pages contained two committed rows. A
writer updated one revision to 999 and held its transaction. Independent SQLAlchemy
readers requested table-specific MVCC/shared with a one-second timeout. Successful
reads were required to return the old committed value, not 999. ODBC pooling was
disabled. Both reader isolation settings were tested with each writer configuration.

| Writer lock level | Writer isolation | Writer read setting | MVCC serializable reader | MVCC read-committed reader |
| --- | --- | --- | --- | --- |
| ROW | serializable | shared | timeout, 1.002 s | timeout, 1.002 s |
| ROW | read committed | shared | committed values returned | committed values returned |
| MVCC | serializable | shared | committed values returned | committed values returned |
| MVCC | serializable | nolock | committed values returned | committed values returned |

Successful reads completed in approximately 0–1 ms at millisecond rounding; this
is a small isolated result, not a latency guarantee. The counter table was removed.
The matrix and documented behavior explain the original held-ROW-writer timeout;
changing the reader isolation or disabling pooling could not remove that writer's
incompatible table access mode.

## Configuration decision

Use **table-specific MVCC/shared for counter access by both writers and readers**.
Do not change the application's session isolation to read committed merely to fix
this problem. Keep source-table read/lock behavior unchanged.

```sql
set lockmode on $ingres.session_probe_revisions
where level=mvcc, readlock=shared;
```

The shared read setting is explicit because inherited NOLOCK must not authorize
uncommitted counter reads. The successful nolock-writer matrix row is evidence
about that tested writer operation, not permission to use dirty counter reads.
MVCC/shared is the intended counter-table contract.

The previous ROW recommendation solved writer/writer contention but was incomplete
for serializable writers interacting with MVCC readers. Historical acceptance is
retained rather than relabeled as full reader/writer acceptance.

## Actual OpenROAD CLI acceptance

A follow-up used temporary counter rules on ii_srcobj_encoded in the isolated
database and a disposable application. Another ODBC transaction held an MVCC
update on an unrelated counter row. All relevant counter access used shared reads.

- Compilation with only a timeout configured failed in the control case.
- Table-specific MVCC/shared startup allowed compilation while the holder remained
  uncommitted.
- Replacement import succeeded under the same initialization and held lock.
- A SQLAlchemy MVCC/shared reader fetched committed counter increments while the
  holder was still active. Its uncommitted dummy-row value was excluded.
- The holder was rolled back and all temporary hooks, procedure, table and app were
  removed. Existing tracking remained healthy.

This establishes the tested CLI writer/reader combination. A corresponding manual
Workbench test has been prepared with a private launcher copy that preserves its
existing inline initialization and appends only the temporary counter-table setting.
That manual MVCC test remains pending. The earlier manual ROW test is not a substitute.

General startup merging, include-file handling, database scoping, schema upgrades,
identity/restart and retention contracts remain separate implementation gates.
No production revision schema or normal status/sync fast path is enabled by this work.

# Experimental revision extension export

`gorak install --export-revision-sql PATH` exports a DBA-reviewable terminal-monitor
script. Use `-` for stdout. Export requires no database connection or project and
refuses to overwrite an existing file. It is mutually exclusive with other install
actions and cannot be combined with the v1-to-v2 `--upgrade` option.

```sh
gorak install --export-revision-sql revisions.sql
```

This is an experimental extension, not a new default installation schema. Ordinary
`gorak install`, `--check`, journal snapshots, status and sync keep their current
behaviour. Do not infer extension health from the existing parent installation check.

## DBA execution contract

Use an isolated source database first. Stop source writers while installing and
configuring clients. Execute as the source owner with rollback-on-error handling;
inspect SQL diagnostics. Configure counter-table MVCC/shared for writers and readers
before resuming writes. Do not silently change application isolation or source-table
locking. Initial support is bounded to single-DBMS-server research, pending identity
and restart certification. No fast status claim follows from applying this script.

The script grants no privileges. The DBA may grant developers SELECT on the two
extension tables; direct counter mutation is unnecessary. The explicit startup
statement is:

```sql
set lockmode on $ingres.gorak_revision_lanes
where level=mvcc, readlock=shared;
```

General startup artifact/backend integration is still pending. Existing helpers do
not automatically inject this setting. Preserve custom startup statements and use
an execution-host include resolver where applicable.

## Schema and capture relationship

The extension creates:

- `gorak_revision_install`: extension version 1, a fresh revision UUID and the
  parent tracking installation UUID copied inside the installation transaction.
- `gorak_revision_lanes`: positive bigint counters keyed by server/session strings.
- `gorak_bump_revision`: increments or initializes the calling writer's lane.
- `gorak_revision_capture`: an INSERT rule on the existing journal event table.

The source rules and `gorak_record_change` are not replaced. Their journal inserts
invoke the extension rule in the same transaction. Rollback therefore removes the
captured event and its counter change together in the tested path. Counters measure
capture activity since extension installation, not the full retained event history.
They are invalidation candidates, not semantic source hashes or commit cursors.

A transactional guard requires exactly one capture-only v2 parent marker before
creating the extension. Existing extension names cause failure rather than replacing
its identity or counters. This guard validates marker shape/version, not every
parent definition or permission; check the parent installation separately first.
Counter overflow fails the update rather than wrapping. Identifier and multi-server
lifecycle certification remain open; keep full verification enabled.

## Generation-bound diagnostic samples

`observe_installed_revisions()` reads extension identity, parent identity and lanes
in one bounded SQL statement. It rejects missing/duplicate markers, wrong versions,
wrong parent mode, zero/invalid UUIDs, mismatched parent identities and invalid lane
rows. Table-specific MVCC/shared reads avoid inherited dirty-read settings.

A `BoundRevisionSample` includes both UUIDs and the bounded `RevisionSample`.
Changing either identity changes the diagnostic result. Exceeding the lane budget
returns no usable lane vector. The query's marker counts are over singleton metadata
tables, not retained event/receipt history. Returned lanes are bounded; total server
query work is not yet benchmarked.

This verifies marker consistency, not stored procedure/rule/column definitions,
physical restore continuity or capture coverage. A restore can restore both UUIDs.
Full reference exports remain required, and this API is not yet wired into normal
source commands or the snapshot publication protocol.

## Live acceptance

The generated SQL was applied to an isolated database with existing healthy v2
tracking. An empty bound sample matched the parent installation UUID. A disposable
OpenROAD app import and compilation, using counter-table MVCC/shared startup,
produced changing samples under the same revision identity. A rolled-back journal
insertion left the sample unchanged. Reapplying the installation failed without
replacing the extension generation or counters.

The disposable app and extension objects were removed afterward. Existing parent
identity and capture definition/column checks remained healthy. No working checkout
or ordinary source database was upgraded.

Next: extension inventory/definition/layout validation, backend startup artifact
lifecycle, and binding into diagnostic snapshot publication. Retain conservative
fallbacks while those gates and identity/retention acceptance remain open.

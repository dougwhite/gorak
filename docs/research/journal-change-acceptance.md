# Journal change and failure acceptance

Checkpoint: 2026-09-14. The generated schema-v2 installation was tested against
actual OpenROAD source tables in an isolated research database. All mutations
targeted a temporary single-procedure application. Original applications and the
working demo were left untouched.

This extends the earlier [source-rule probe](source-rule-coverage.md) with the
current installer, consumer and application mapper. It does not enable selective
status or sync without a full reference comparison.

## Source changes

Imports, compilation and deletion used OpenROAD CLI commands over SSH. Journal
events were polled through ODBC and mapped using current metadata and captured
ancestry. Fresh XML exports supplied semantic signature comparisons.

| Operation | Captured events | Mapping result |
|---|---:|---|
| Create application and procedure | 14 | Only the temporary application |
| Replace application with a procedure script edit | 23 | Only the temporary application |
| Compile application | 3 | Candidate application plus conservative full fallback |
| Replace description and source include | 24 | Only the temporary application |
| Delete procedure | 5 | Only the temporary application |
| Delete application | 6 | Deleted application resolved from captured ancestry |

The script edit changed the exported signature. Compilation left that signature
unchanged, despite events on component and encoded-object rows. Compilation
deleted/reinserted a component without a matching historical entity tombstone, so
the mapper correctly requested full comparison. Metadata/include replacement
changed the exported signature. These are candidate-mapping checks, not proof of
complete source coverage or selective snapshot continuity.

## Capture failure

A temporary check constraint allowed existing journal rows but rejected new event
IDs. With that constraint active:

- An owner SQL update to the temporary procedure's entity description failed.
  Before/after entity IDs and descriptions were identical.
- An OpenROAD replacement import containing another script edit reported SQL
  errors. A fresh export matched the original application's pre-failure semantic
  signature.

This demonstrates rollback for the tested SQL update and preservation of the
application for the tested replacement import. It does not establish atomicity
for every multi-transaction OpenROAD operation. Terminal-monitor diagnostics were
checked in addition to process exit codes.

The fault constraint was removed using DROP CONSTRAINT with RESTRICT before
continuing the remaining operations.

## Definition health

The installation check now reassembles catalog SQL text and compares the capture
rules and procedure with the generated definitions. A fresh live installation
reported definitions_verified=true.

One update rule was replaced with the same name and target but a different action
literal. The check reported its modified definition and definitions_verified=false.
Restoring the generated rule restored a successful check.

This checks stored definitions, not all schema properties or runtime conditions.
Additional constraints, disabled execution, incomplete table coverage, restore
continuity and concurrent changes still require separate validation.

## Cleanup and remaining gates

The temporary application, fault constraint and all test tracking objects were
removed. Catalog checks confirmed tracking objects were absent. Local raw logs
and XML evidence remain outside version control; machine-specific identifiers are
not part of the repository.

Remaining acceptance includes Workbench saves, frames and referenced strings/images,
rename/move and version operations, large transactions crossing consumer batches,
concurrent exports and commits, restore detection, retention, and measured overhead.
The mandatory full-export reference remains in place until snapshot continuity and
invalidation are proven.

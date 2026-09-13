# OpenROAD source-rule coverage probe

Research checkpoint: 2026-09-13. Temporary rules were installed on actual OpenROAD
source tables in an isolated acceptance database. All source mutations targeted a
synthetic single-procedure application. This is a coverage probe, not a production
installer or comprehensive statement about every Workbench save path.

## Installation privilege

The inspected source tables are owned by `$ingres`. Creating a rule from an ordinary
`ingres` ODBC connection failed with SQLSTATE 42503 and error 6313: permission to
apply a rule to the source table was denied. That attempt was rolled back.

A create-and-rollback test using the SQL terminal monitor's documented `-u$ingres`
owner-identity option succeeded. The subsequent temporary installation used that
identity, not changed table ownership or grants that weakened source-table access.
This means a production installer must distinguish privileged database bootstrap
from ordinary ODBC source operations. Do not assume an ordinary DBA login is enough
or require ongoing use of the privileged identity by developers.

References: [CREATE RULE permissions](https://docs.actian.com/ingres/12.0/SQLRef/CREATE_RULE.htm)
and an [Actian maintenance example using the owner identity](https://docs.actian.com/actianx/12.0/Upgrade/Recreate_Users__Groups__and_Roles.htm).

## Instrumentation

Twenty-four AFTER rules covered INSERT, UPDATE, and DELETE on eight tables:

- `ii_srcobj_encoded`
- `ii_entities`
- `ii_components`
- `ii_applications`
- `ii_incl_apps`
- `ii_stored_strings`
- `ii_stored_nstrings`
- `ii_stored_bitmaps`

A small procedure appended sequence identity, table name, old/new object identity,
and operation to a separate event table. Readers used MVCC. The journal did not
hash or copy source payloads. Only read access to the event table was granted to
the ordinary inspection connection.

## Observed operations

| Controlled operation | Source tables with captured events | OpenROAD SSH invocation time |
|---|---|---:|
| Whole-app replacement containing a procedure script edit, without forced compilation | encoded objects, entities, components, applications, includes | 0.484 s |
| Explicit compileapp | components, encoded objects | 0.414 s |
| Whole-app replacement changing description and adding a source include | encoded objects, entities, components, applications, includes | 0.396 s |
| Delete procedure | entities, components, encoded objects, applications | 0.377 s |
| Delete application | applications, encoded objects, includes, entities | 0.388 s |

Times include SSH/OpenROAD invocation, exclude XML upload, subsequent log retrieval,
and event queries, and have no uninstrumented control. They do not establish rule
overhead or whole-development-loop latency.

Whole-app imports generated deletes and inserts for entity rows, not merely in-place
updates. Explicit compilation deleted/reinserted a component row and updated encoded
source. An added include produced an additional include-row insert. The observed
application deletion left journal events after the source identities disappeared.

The eight-table probe was not a proof that every table is necessary/sufficient.
No string/image-table events occurred for this simple procedure. Direct Workbench
saves, complex frames/images, Unicode, version operations, object renames, chunk-key
changes, and large application imports remain acceptance work. The metadata/include
probe replaced an entire app, so it cannot isolate which metadata fields independently
cause an event on a Workbench save.

## Consequences for the installer and event schema

1. Privileged bootstrap must verify ownership, required capabilities, pre-existing
   object names, installation generation, schema/rule versions, and grants. Runtime
   clients should have only the permissions needed for their normal operations.
2. Tombstones must preserve enough old identity context to resolve a deleted object:
   table/key, parent/base/version relationships and, where appropriate, old name/type.
   Looking up an entity after deletion is insufficient. Updates that change keys or
   parentage must invalidate both sides.
3. Events are candidate invalidations, not a semantic source diff. Compilation and
   replacement operations can change IDs and encoded bytes without a corresponding
   readable source edit. Do not expose raw rule events as user-facing conflicts.
4. The source transaction must roll back if required event capture fails; silently
   continuing would make the fast path unsound. Prove this explicitly in the next
   fault-injection test before shipping installation.
5. Long transactions, chunk-heavy saves, reader isolation, consumer acknowledgment,
   and retention still need performance/correctness gates from the journal design.
6. Installer execution must check database diagnostics, not only the terminal monitor
   process exit code: a SQL error can be printed while the process returns success.

## Cleanup and retained evidence

After the tests, the disposable application was deleted. All 24 temporary rules,
the journal procedure, and its sequence were removed; absence was checked through
catalog queries. The event table and local raw logs were retained for inspection.
No original application source was edited and no rule remains attached to source
tables from this probe. Machine-specific names and raw extracts are not tracked.

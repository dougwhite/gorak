# DBA-managed source hook installation

Generate the script locally, without a database connection or Gorak project:

```sh
gorak install --export-sql gorak-install.sql
```

Use `--export-sql -` to write only the script to stdout. Existing output files are
never overwritten. The exported file contains no credentials, host, or database
name. The DBA chooses the target when applying it; a server-generated installation
UUID is created separately in each target.

## Current scope

This first script installs **capture-only schema version 2**: an installation record,
a change-event table, a consumer acknowledgment table, a sequence, a procedure, and 24 rules on eight source-related
tables. It preserves old/new identity context, including entity names and parent,
base/version relationships and chunk keys where available. It does not copy source
payloads into the journal.

This is an initial installation artifact for validation, not a completed incremental
sync feature. Source-processing integration, retention/pruning, full health certification, general migrations, and
complete source-table coverage are not implemented. Events accumulate. Do not deploy
indefinitely on a busy source database without an agreed lifecycle. Existing names
cause installation to stop; the script never drops or replaces an installation.

The DBA must first provision and initialize an OpenROAD source database using the
site's normal procedures. Database creation is not performed by this script. Quiesce
source writes during installation and review the privileges and generated SQL.

## Apply using the Ingres SQL terminal monitor

The required identity is the source-table owner, `$ingres`. The SQL client can run
on the database host **or on a suitably authorized client through a vnode**. A
Windows-client owner-identity connection and this generated installation script
were verified against an isolated remote source database. Authorization depends on
the authenticated account and installation policy, not simply on having sql.exe.

Linux shell, with an initialized Ingres client environment:

```sh
II_TM_EXIT_ON_ERROR=rollback sql '-u$ingres' node::source_db < gorak-install.sql
```

Windows cmd.exe:

```bat
set II_TM_EXIT_ON_ERROR=rollback
sql "-u$ingres" node::source_db < gorak-install.sql
```

PowerShell (single quotes keep `$ingres` literal):

```powershell
$env:II_TM_EXIT_ON_ERROR = 'rollback'
Get-Content -Raw .\gorak-install.sql | & sql '-u$ingres' 'node::source_db'
```

These are examples with generic targets. Configure the Ingres client environment
and vnode first. No DBA password belongs in the generated file.

The script uses terminal-monitor `\nocontinue`, disables autocommit, and requests
transaction rollback on errors. Set `II_TM_EXIT_ON_ERROR=rollback` as shown so terminal
monitor also rolls back before exiting on errors. Do not continue past SQL failures
or rely on its process exit code alone. Other SQL tools must implement equivalent
stop-on-error/transaction semantics and handle procedure bodies as single statements;
the exported file includes terminal-monitor commands and is not generic SQL-client
input.

On success, the final query displays one `gorak_tracking_install` record with version
2, a nonempty installation UUID, and mode `capture_only`. The DBA should inspect the
log and verify the expected tables, procedure, sequence and all 24 rules exist. This
record alone is not a future runtime health guarantee: missing/modified hooks must
still be checked beyond the inventory diagnostic below.

No grants are issued automatically. The DBA decides who can read tracking data;
ordinary developers do not need the owner identity. Do not grant journal mutation
rights broadly or treat developer-controlled acknowledgments as safe retention policy
before that protocol is implemented.

## Evidence and limitations

See [real source-rule coverage](research/source-rule-coverage.md) and
[transaction/MVCC probes](research/change-journal.md). The exported script was applied
through the Windows SQL client to an isolated target, then removed. A deliberately
invalid rule target was used to check rollback of partially created installation
objects. Migration/removal commands and production-scale
acceptance remain future work.

[Actian documents](https://docs.actian.com/ingres/11.2/SysAdmin/II_TM_EXIT_ON_ERROR.htm)
the relationship between `\nocontinue` and `II_TM_EXIT_ON_ERROR=rollback`.

## Check an installation

From a configured project using ODBC:

```sh
gorak install --check
```

The normal database/ODBC connection overrides are accepted. This command reads
catalogs, the owner-qualified installation record, and checks read access to the
event table without scanning events or source payloads. It makes no schema or source
changes and disposes its connection after checking. Configure developer SELECT
access through the DBA; owner impersonation is not performed by Gorak.

JSON output lists missing tables, sequence, procedure and rules (including incorrect
rule targets), missing or modified rule/procedure SQL definitions, unsupported
version/mode, and invalid installation identity. Exit 1
means a detected problem or database-access failure; exit 0 means the expected
capture-only inventory, definitions and marker were found. Connection/permission errors use the
normal CLI error reporting.

A successful check reports `capture_only_inventory_present` and
`definitions_verified: true` and `incremental_ready: false`. Catalog SQL segments
are reassembled and compared with Gorak’s generated definitions, allowing keyword
case, whitespace, and the source owner qualification added by Ingres. String
literals and quoted identifiers remain significant. Missing or modified definitions
make the check incomplete; no schema upgrade is needed for this check.

It does **not** certify table column types, extra constraints, enabled-rule
execution, complete source coverage, or continuity
after a database restore. It is a point-in-time diagnostic, not permission to bypass
a full source comparison. Same-named objects owned by a developer cannot satisfy
the check. Source writes should remain quiescent while diagnosing an installation
being changed by a DBA.

The catalog fields follow the
[Actian standard catalog reference](https://docs.actian.com/ingres/11.0/DatabaseAdmin/Standard_Catalogs_for_All_Databases.htm).
The missing-installation path was also verified read-only against an isolated live
source database: it reported both missing tables, the sequence, procedure, and all
24 missing rules. Complete and damaged inventories are covered by automated tests;
live complete-installation checking remains an acceptance item.

## Direct installation

Run `gorak install` from a configured project to apply the schema. ODBC settings
are required for preflight and post-install checks. Execution follows
`GORAK_BACKEND` / `--backend`: remote uses the configured Windows SSH host;
local invokes `sql` from the local environment. Finding a local SQL executable
never overrides a remote backend. A failed remote operation never falls back to
local execution.

The SQL session requests `-u$ingres`; the authenticated connection must already
permit this identity. No credentials are passed to SQL or SSH. Remote installation
stages a unique SQL file in the configured Gorak root, executes it through
PowerShell and the Windows SQL client, and removes the remote file after execution.
The remote root must already exist; existing remote helper installation provides it.

Direct installation adds SELECT grants on the two capture tables and SELECT/INSERT
on the consumer acknowledgment table for the configured ODBC user, inside the
installation transaction. It grants no source or captured-event write access. The standalone `--export-sql` artifact remains grant-free so
the DBA can choose site-specific permissions. SQL and logs are retained under
`.openroad/installations/<operation>/`.

A complete existing version 2 inventory is a no-op; version 1 requires explicit upgrade. Partial installations are refused rather
than repaired or replaced. SQL errors, nonzero process exits, timeouts and failed
postchecks do not report success. If verification fails after SQL completes, the
installation may exist: inspect the retained log and permissions before retrying.
Timeouts/disconnections can leave remote work or a staged file behind; this command
does not automatically drop objects or retry an uncertain installation.

The execution target database and ODBC database must match. The operator must also
ensure the SQL vnode and ODBC host refer to the same server; this initial version
does not prove server identity across transports. Installation remains capture-only
and should occur with source writes quiescent. Local execution is covered by
automated transport tests; remote execution is additionally tested against an
isolated source database.

A [journal preview and replayable consumer primitive](journal.md) is now available.
It does not yet process source changes or make status incremental.

## Upgrade v1 to v2

```sh
gorak install --upgrade
```

This uses the same configured execution backend as installation, then verifies
version 2 over ODBC. It preserves installation identity, events, capture rules,
and procedure. Existing v1 journal consumers remain readable until upgraded.

For DBA-managed execution:

```sh
gorak install --upgrade --export-sql gorak-upgrade.sql
```

Apply with the same owner identity and rollback/error-stop environment as the
installation script. The export contains no grants. The DBA must grant the reader
SELECT and INSERT on `gorak_journal_acks`; direct upgrade supplies those grants
for the configured ODBC account. Other developer accounts need their own DBA grants.

The SQL validates exactly one v1 capture-only marker through a temporary guard
table with a CHECK constraint. A wrong version aborts and rolls back. It creates
the acknowledgment table, updates the version, then drops its newly created guard
table within the transaction. It never drops existing capture data or rules.
Unknown/partial installations require DBA review. Quiesce source writes during
schema administration.

Live isolated acceptance verified v1-to-v2 identity preservation, populated
consumer polling, rejection/rollback when the upgrade was applied to v2, and fresh
v2 installation. Temporary tracking objects were removed afterward.

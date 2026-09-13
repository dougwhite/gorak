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

This first script installs **capture-only schema version 1**: an installation record,
a change-event table, a sequence, a procedure, and 24 rules on eight source-related
tables. It preserves old/new identity context, including entity names and parent,
base/version relationships and chunk keys where available. It does not copy source
payloads into the journal.

This is an initial installation artifact for validation, not a completed incremental
sync feature. Consumers, retention/pruning, health-check automation, upgrades, and
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
1, a nonempty installation UUID, and mode `capture_only`. The DBA should inspect the
log and verify the expected tables, procedure, sequence and all 24 rules exist. This
record alone is not a future runtime health guarantee: missing/modified hooks must
still be checked by the forthcoming health-check service.

No grants are issued automatically. The DBA decides who can read tracking data;
ordinary developers do not need the owner identity. Do not grant journal mutation
rights broadly or treat developer-controlled acknowledgments as safe retention policy
before that protocol is implemented.

## Evidence and limitations

See [real source-rule coverage](research/source-rule-coverage.md) and
[transaction/MVCC probes](research/change-journal.md). The exported script was applied
through the Windows SQL client to an isolated target, then removed. A deliberately
invalid rule target was used to check rollback of partially created installation
objects. Automatic installation, migration/removal commands, and production-scale
acceptance remain future work.

[Actian documents](https://docs.actian.com/ingres/11.2/SysAdmin/II_TM_EXIT_ON_ERROR.htm)
the relationship between `\nocontinue` and `II_TM_EXIT_ON_ERROR=rollback`.

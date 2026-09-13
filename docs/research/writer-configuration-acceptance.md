# Writer configuration and owner-rule acceptance

Date: 2026-09-14. Follow-up to [writer-session counters](session-revision-acceptance.md).
These isolated live experiments did not install revision tracking or change saved
client settings, database defaults or the active Workbench process.

## Owner-defined rule invoked by another user

An authorized owner connection created randomly named scratch source/counter tables,
a counter procedure and insert/update/delete rules. The existing ordinary ODBC user
received SELECT/INSERT/UPDATE/DELETE on scratch source and SELECT on counters. No
counter mutation or explicit procedure execution privilege was granted to that user.

Two connections of that ordinary user then exercised the source rules:

- Each rule recorded the server/session identity of the actual calling connection.
- One writer committed while the other remained uncommitted, taking 3.642 ms in the
  measured case. Both counters were correct after the first writer committed.
- Direct counter UPDATE was rejected with SQLSTATE 42503.
- Source update/delete rollback also rolled back the procedure's counter changes.
- The ordinary user successfully applied a table-specific ROW setting to the
  owner-qualified counter table. Concurrent writes then succeeded independently.

This proves the tested owner/caller boundary, not every installation's grant policy.
The table-specific command was issued before source transactions:

```sql
set lockmode on "$ingres".session_probe_revisions where level=row, timeout=2;
```

Both source connections otherwise used explicit MVCC in this experiment. All
scratch rules, procedures and tables, including their grants, were removed.

## Fresh session defaults

A fresh ODBC connection and a fresh Windows terminal-monitor connection both
reported the following DBMSINFO settings against the same isolated server:

| Setting | Value |
| --- | --- |
| Server version | Ingres 12.0.0 |
| session_locklevel | default |
| session_readlock | shared |
| session_isolation | serializable |
| session_locktimeout | 0 |

`default` is a reported session setting, not proof of the effective lock level for
every table. Existing table-specific overrides are not represented by that value.
These measurements also do not describe an already running Workbench session.

## Actual OpenROAD import and compilation

A temporary owner audit procedure inserted only session_locklevel,
session_readlock and session_isolation into a scratch table. Temporary rules on
insert/update/delete of ii_srcobj_encoded called it. Existing capture rules were
preserved. A new isolated probe application was imported with `w4gldev backupapp`
and compiled with `w4gldev compileapp`; audit rows were collected separately for
each phase. The scratch application, audit rules, procedure and table were removed.

The first run inherited the Windows SSH process environment. Both source-writing
phases reported `default / shared / serializable`.

A second run applied this setting only to each disposable child process:

```bat
set "ING_SET=set lockmode session where level=row"
```

Both import and compilation then reported `Row / shared / serializable` from the
source-write rule. Thus the environment setting reached the actual source-writing
session and was still in effect at those observed mutations. No saved environment
or packaged helper was edited. The experiment used a session-wide setting; it does
not prove a table-specific ING_SET override survives all application behavior.

The packaged Gorak helpers currently do not explicitly choose a lock level. They
inherit their process environment. Gorak must not infer safe counter locking merely
from a configured ODBC reader or successful tracking inventory check.

## Table-specific initialization through real source writers

A subsequent isolated experiment installed a temporary session-counter procedure
behind scratch rules on ii_srcobj_encoded, then held an uncommitted ROW lock on
one unrelated counter row from an ODBC connection. Only a disposable application
was compiled/imported. A two-second timeout bounded the control failure.

With only the timeout configured, compilation failed while that row remained
locked. With this additional process-local initialization, compilation and then
replacement import both succeeded while the same unrelated row remained locked:

```sql
set lockmode session where timeout=2;
set lockmode on $ingres.session_probe_revisions where level=row;
```

The actual test used a randomly named scratch table. This is a behavioral check
of the table-specific setting through OpenROAD, beyond reading a session default.
The test did not change source-table lock levels or saved environment settings.
The held transaction was rolled back, and temporary hooks, counter table,
procedure and disposable application were removed. Existing tracking stayed healthy.

This validates explicit table-specific statements in ING_SET. Combining arbitrary
existing statements, database-specific startup settings and include files still
needs implementation and acceptance; the test used controlled startup strings.
A settings-only audit subsequently captured a user-driven Workbench save; see
the results below. Configured table-specific ROW acceptance in Workbench remains
separate from these baseline settings.

## Actual Workbench save: baseline settings

The user changed a button label in the retained isolated test application's simple
frame, saved it, and closed the frame editor using the existing Workbench session.
A fresh application export verified the requested label change. The temporary audit
recorded 29 source writes, all with these reported settings:

| Setting | Value |
| --- | --- |
| session_locklevel | default |
| session_readlock | Nolock |
| session_isolation | serializable |

This differs from the fresh CLI session's shared-read setting. It confirms why
Gorak cannot use its own connection settings as evidence for Workbench writers.
`Nolock` describes reads; it does not establish row-level write locking. Likewise,
`default` does not reveal every effective table-specific setting.

The settings-only audit rules, procedure and table were removed after the fresh
export check, and existing tracking remained healthy. The intentional label edit
remains in the isolated test app. No counter rules or startup configuration were
installed into the user's Workbench session by this test.

Next acceptance must explicitly configure the proposed table-specific ROW startup
and verify a Workbench save under that configuration. The baseline save above is
not that acceptance and does not authorize enabling revision counters for all
existing Workbench sessions.

## Restart and identity boundary

No server or VM was restarted. The earlier sequential reconnect test demonstrated
session-key reuse with counters correctly continuing from their retained values.
That supports keeping counters across reconnects; it is not restart acceptance.

DBMSINFO's server address is not documented as a durable server-incarnation ID.
Do not reset a counter based on a presumed new connection/server lifetime. If a
retained key is reused sequentially, continuing its counter avoids losing progress.
Possible concurrent collisions across server/node configurations still need testing;
server address plus session ID is not yet a certified installation-wide key.
A physical restore can also restore counters and requires the generation contract
already described in the checkpoint design.

## Next implementation gates

1. Provide an explicit writer initialization contract. Preserve existing ING_SET
   statements and include-file configuration; do not silently replace custom shop
   settings. Table-specific initialization passed controlled real import/compile tests;
   preserving arbitrary existing startup configuration remains unimplemented.
2. Verify a Workbench save under the explicit table-specific initialization
   contract. Its existing-session baseline is now captured above; its configuration
   was not changed.
3. Certify identity composition, lengths, overflow and restart behavior. Do not add
   online counter deletion: the previous race rejected a writer.
4. Implement bounded revision observation and safe full-comparison fallback behind
   diagnostics, with the full-export reference retained until continuity is proven.

Existing tracking passed its inventory/definition/column checks after cleanup.
These are research results; normal status/sync and tracking schema remain unchanged.

## Primary references

Actian documents process-local startup statements and include-file support in
[ING_SET](https://docs.actian.com/ingres/12.0/SysAdmin/ING_SET.htm).
The transaction restriction on lock-level changes is documented in
[LOCKMODE](https://docs.actian.com/ingres/12.0/SQLRef/LOCKMODE.htm).
Identity fields are described in
[DBMSINFO](https://docs.actian.com/actianx/12.0/SQLRef/DBMSINFO_Function.htm).

# Managed revision mode

Managed revision mode gives `gorak status` and the `gorak sync --push` preflight a
quiet fast path. It requires direct ODBC and the optional revision extension.
Normal projects keep their existing full-comparison behavior until configured.

The initial implementation deliberately uses whole-snapshot invalidation. If a
complete revision vector is unchanged, Gorak compares disk and baseline against
compact semantic hashes from a verified database snapshot. Any changed vector,
expired checkpoint, different scope or damaged cache triggers another full XML
comparison. It does not yet selectively refresh changed applications or decode
`ii_srcobj_encoded`.

## Deployment contract

This mode is for a managed, single-DBMS-server source database. Before enabling it:

1. Install and check the parent tracking schema using `gorak install` and
   `gorak install --check`.
2. Stop and drain source writers. Export the extension with
   `gorak install --export-revision-sql revisions.sql`, and have the database owner
   review and execute it. Grant the developer account SELECT on the extension
   marker and lanes. Do not grant ordinary clients counter mutation permissions.
3. Configure **all** Workbench and other source writers with table-specific
   MVCC/shared locking on `$ingres.gorak_revision_lanes`. The earlier controlled
   Workbench acceptance establishes the tested configuration; Gorak does not edit
   Workbench shortcuts or reconfigure already-running sessions.
4. Run `gorak install --check-revision`. Review the capture-coverage and operational
   limits in the research documentation. Structural checks alone are not a claim of
   universal OpenROAD-version or save-path certification.
5. Add the returned revision UUID to the project's local `.env`:

   ```dotenv
   GORAK_SQL_BACKEND=odbc
   GORAK_REVISION_GENERATION=<revision_id returned by the check>
   GORAK_WRITER_ENCODING=cp1252
   ```

   Use the encoding of the execution host's startup files. `cp1252` is the default
   for the tested Windows setup, not a universal Ingres charset choice.
6. For SSH, run `gorak remote install`. Helper version 7 includes a deterministic
   Python zipapp built from the same worker modules used locally. The Windows host
   needs Python 3.12 or newer available as `python`, plus its existing OpenROAD
   installation. Managed operations reject an outdated helper manifest.
7. Bind a fresh source baseline using `gorak sync --bind` if necessary, then run
   `gorak status` to establish the first full snapshot. A subsequent quiet status
   should report `observation.mode: revision_reuse`.

Setting `GORAK_REVISION_GENERATION` is an explicit adoption of this contract, not an
automatic installation or discovery switch. Generation mismatches and damaged
tracking stop configured operations. Do not work around those failures by copying an
old UUID into the database or deleting a quarantine marker.

## Everyday commands

Use the ordinary commands:

```bash
gorak status
gorak sync --push
gorak test
```

Status reports whether it reused a snapshot or performed a full refresh. A no-change
push can finish after the verified preflight. Actual imports still retain their
fresh object conflict checks, compilation and post-import verification. `gorak test`
still runs the configured test applications; it does not implicitly sync first.

Configured local and SSH imports, exports, fresh-process compilation and run/test
launches use the shared execution-host worker. It selects `w4gldev` from the child's
`II_SYSTEM`, resolves existing database-specific startup settings on that host,
preserves their SET statements and appends the lane-table setting. An empty process
value falls back to the installation symbol. The generated include is scoped by
source **database name**, not by vnode. A runtime connection to another installation
with the same database name is outside the current deployment contract.

Before each export, import or run, Gorak reads the generation through the OpenROAD
execution host's selected Ingres installation and vnode. That UUID must match the
ODBC generation. Checkpoints also bind the non-secret ODBC endpoint settings. Quiet
status observes the configured ODBC database without launching a source-host process.
Vnode retargeting must happen offline, followed by a fresh binding; independent
database clones must receive fresh generations before use. The route check does
not lock vnode configuration against concurrent administrator changes. Managed run
environment overrides cannot change `II_SYSTEM`, `II_CONFIG`, `II_INSTALLATION` or
`II_GCN*`; configure the execution host consistently for source and run operations.

Startup files live through the child process and are removed afterward. The runner
owns a temporary parent directory so timeout termination can clean worker leftovers.
An abrupt machine failure may leave temporary files; removing them is safe only after
confirming their processes have stopped. Windows temporary-root permissions must be
appropriate for potentially sensitive startup SQL.

## Checkpoints and continuity

`.openroad/revision-checkpoint.json` contains a format version, target and scope,
configured and observed generations, complete lane vector, creation time, per-object
semantic hashes, and a checksum of the payload. Publication uses a temporary file,
fsync, atomic replacement and directory flush where supported. Baseline/source files
are not advanced by status.

A quiet observation checks installation health and the vector before and after the
local comparison. A full refresh publishes only if that window remains stable.
Any committing writer that increments capture changes the vector, including a
transaction with an event ID allocated earlier than another committed event.
Allocated event IDs are never used as commit watermarks.

Checkpoints expire after 15 minutes, without extending their life on reuse. Expiry,
clock rollback, scope change, a partial/over-budget vector, corruption or an older
checkout causes full refresh. A vector can contain at most 4096 lanes before the
bounded reader declines reuse. Checkpoint payloads are limited to 32 MiB; oversized
snapshots continue through full comparisons without publishing a partial cache.

There is no server-side consumer cursor or acknowledgment for this mode. A checkout
stores evidence of a **complete snapshot of the tracked application scope**, not progress through event IDs.
Consequently an offline or abandoned checkout cannot hold journal retention open,
and event/receipt pruning cannot make it miss changes: the vector is independent of
that history. Existing journal diagnostics retain their own receipt/history rules;
this feature does not introduce an event-history pruning command.

For an explicit oracle check, use:

```bash
gorak journal --verify-revision
```

It compares the cached semantic hashes and resulting plan with fresh full XML.
A disagreement or an observed broken tracking installation quarantines the current
generation in `.openroad/revision-quarantine.json`. Repairing the objects alone does
not clear that quarantine: a new generation and fresh snapshot are required.
Concurrent source activity invalidates the observation and asks for a retry.

The older `--verify-selective` diagnostic remains separate and retains its mandatory
full reference, event mapping and private journal observer. It is not the normal
quiet path.

## Restore, restart and maintenance

A physical restore can restore the source, counters and UUIDs together. No
in-database token can automatically distinguish that from the original state.
The supported authority is an explicit DBA generation transition:

1. Stop and drain all source writers.
2. Complete the restore or clone, DBMS restart, capture-definition change or lane maintenance.
3. Export `gorak install --export-revision-reset-sql reset.sql` and execute the
   reviewed script as the database owner **before allowing clients to reconnect**.
4. The guarded transaction assigns a fresh revision UUID and clears old counter
   lanes, preserving source and journal history. On error it must be rolled back.
5. Update clients to the new UUID and allow them to establish full snapshots.

Never delete/consolidate lanes online, reuse an old generation, or resume a restored
installation before rotating its generation. The implementation rejects old client
configuration and old checkpoint bindings after the supported transition. It does
not claim to detect a restore when this operator contract is violated.

## Performance and remaining limits

The isolated acceptance includes real Windows import/compile, disk edits and push,
quiet CLI runs, test XML collection, generation rotation, an old checkout checkpoint,
broken-hook quarantine, and database application deletion/conflict blocking. See
[acceptance results](research/managed-revision-acceptance.md).

The quiet database path performs no XML export and no event/receipt-history scan.
Local source and baseline comparison still parses/hashes local files; large-source
performance is not yet bounded independently of local source bytes. The small
acceptance timings are not a gigabyte-scale performance claim. Dirty vectors and
periodic expiry still pay the XML cost. Native encoded-source decoding and later
selective refresh can reduce that cost without changing this checkpoint contract.

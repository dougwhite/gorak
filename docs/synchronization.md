# Synchronization status and safety gates

M2 is in progress. The CLI uses a shared three-way planner and a staged pull
executor. Push retains its existing executor behind conservative safety gates.
Bidirectional synchronization is not yet complete.

```sh
gorak status
gorak sync --bind
gorak sync
gorak sync --push
```

`status` reads disk, cached baseline XML, and freshly exported database XML. It
returns JSON with `baseline_target` and `changes`. It does not change project files,
advance baselines, or import database source. Read-only comparison still invokes
OpenROAD export helpers and may create remote export artifacts. Full XML scans are
intentional in this first version; efficient metadata-driven scans come later.

Each change identifies a key (`app` or `app/component`), disk/database change kinds,
and an action: `pull`, `push`, `converged`, or `conflict`. Unchanged objects are omitted.
`converged` means both sides now agree but differ from the cached baseline. Divergent
edits and delete-versus-edit are conflicts. An app deletion is also checked against
changes to its child components. Unsupported local metadata/markup edits are
reported as invalid source conflicts, not silently treated as missing objects.

## Bind existing caches

Old caches do not identify their database. `gorak sync --bind` compares the current
database with the cached baseline and records the configured target only if it
matches. It does not push or pull source. If the database has changed, reconcile
or explicitly re-export into an appropriate checkout before binding. Do not erase
unknown baseline data just to bypass a conflict.

The record is `.openroad/sync-target.json`, written atomically and excluded from
Git with the rest of `.openroad`. A new cache-free sync can bind automatically;
a dry run never creates the binding. The target includes backend, executing host,
vnode, and database, without credentials. A changed configured target is rejected
by status/sync and the CLI export/import commands. Use a fresh checkout/cache for a
new target. This checks configured identity: it does not yet detect a server-side
vnode remapping or database replacement under the same name.

## Current execution policy

- Conflicts stop both directions before execution.
- Pull stops if disk has pending changes, even to unrelated components.
- Push stops if the database has pending changes, even to unrelated components.
- Pull supports database-side component and application deletions and application
  metadata changes. Unrelated files such as notes survive application deletion.
- Push still blocks pending deletions.
- Existing push metadata/type restrictions continue to apply.

Older projects without source companions use their cached XML to reconstruct existing
components and application metadata for comparison. This preserves opaque metadata
and distinguishes unchanged legacy exports from genuinely new components. The cache
is still required for those checkouts; portable, cache-free reconstruction requires
source companions. Re-exporting is not required just to inspect legacy source.

## Staged pulls and recovery

Pull exports affected applications into `.openroad/pulls/OPERATION/stage`, checks
fresh database exports against the staged XML, and verifies the local snapshot
before installing source and baseline files. Converged changes advance the baseline.
Deleted applications remain in a local tracked-applications record so a later
re-addition in the database can be discovered.

Before-images and a change journal remain under the operation directory. A failed
installation attempts to restore files it wrote, preserving subsequent external
edits. `.openroad/pull-pending.json` blocks further source operations after an
interrupted or failed installation: inspect the referenced journal and before-images
and reconcile source/cache before removing that marker. Automatic recovery is not
implemented. A stale `.openroad/pull.lock` likewise requires checking that no pull
process is still active before removal.

File replacement is atomic per file, not across the whole project. Revalidation is
optimistic: external Workbench/file writes can still race the final checks. CLI source commands within a project now share `.openroad/mutation.lock`, held
across planning, backend calls, and local installation. This includes sync/bind,
component import, app/component export, scaffolding, configuration, defaults
flattening, and encoding. An overlapping command fails immediately. The lock records
its process ID and operation; an ordinary exception releases it. After a killed
process, confirm that the recorded operation has stopped before removing its lock.
Do not remove recovery markers merely to bypass this check.

This is a checkout lock, not a database lock. Other checkouts, Workbench, editors,
and direct Python orchestration calls do not participate. Commands outside a Gorak
project have no checkout lock, including explicit output paths into another project.
Status remains read-only and can observe a concurrent mutation. Stronger push
validation and database-side deletion execution remain M2 work.

## Push snapshots and interrupted operations

Push fingerprints the project before preflight and rechecks it before each import
and after verification. Added and removed files count as changes, as do edits to
existing files. Verification compares imported components with the submitted XML,
not a potentially changed disk file. Creation paths recheck database names just
before import to detect objects that appeared after planning. Application metadata
updates retain their full-application drift check; script imports retain their
component baseline comparison.

Before execution, push retains a plan and copies of cached baselines under
`.openroad/pushes/OPERATION`. A `.openroad/push-pending.json` marker blocks later
mutations and status/sync comparison if execution does not finish successfully.
Inspect the plan, submitted/returned XML, import logs, and retained baselines before
reconciling the database and local cache. Do not blindly retry a failed remote call:
the database may have accepted it even if its response was lost.

All push caches, including existing script imports, are staged until imports and
source checks succeed. Cache installation uses before-images and attempts rollback
on write failure, while preserving subsequent external edits. It is not a multi-file
filesystem transaction; a killed process can still leave partial cache installation.
The pending marker remains until installation completes. Snapshot checks remain
optimistic and cannot exclude a Workbench change between a check and an import.

### Verify and finish an interrupted push

Run `gorak recover push` in the affected project. It takes the checkout lock, requires
the original verified target binding, and compares disk with fresh database exports.
If both sides agree, it stages fresh baseline XML, rechecks the project and database,
installs those baselines, and clears the pending push marker. Recovery artifacts and
the original marker are retained under `.openroad/pushes/recovery-OPERATION`.

Recovery never imports database source or rewrites readable disk source. If disk and
database differ, it stops with the marker intact. A partially successful push still
requires deliberate reconciliation; this command does not choose a winning side or
roll back database writes. Pull recovery is still manual. A stale mutation/push lock
from a killed process must be inspected separately before running recovery.

## No-change push cost

When the verified planner reports only unchanged objects, push returns immediately
without repeating application/component inventory calls or creating push artifacts.
The full safety comparison still exports tracked applications. A following `status`
command performs another independent comparison.

A seven-application remote sample measured 14.6 seconds before this shortcut and
9.5 seconds afterward. These are individual wall-clock observations, not a benchmark
guarantee. Almost all measured time was in SSH/SCP subprocesses; local processing
was about 0.1 seconds in the first sample. Export execution and transport startup
are combined in the SSH timings. Metadata-based change detection and batching
remain future work; ODBC alone does not remove full XML exports.

The full comparison now exports up to four independent applications concurrently.
Results are consumed deterministically, and an export failure aborts comparison;
workers finish before temporary files are removed. On POSIX clients, CLI operations
reuse SSH/SCP connections through a private per-invocation control-socket directory.
The short-lived master expires after ten idle seconds. Windows clients retain their
normal SSH behavior; no persistent SSH configuration is edited.

A further seven-application live sample measured 5.4 seconds sequentially after
reducing unrelated VM load, 3.2 seconds with concurrent exports, and approximately
2.1 seconds with connection reuse. Two/four/eight export concurrency measurements
were approximately 2.2/2.1/2.1 seconds with reuse; four limits VM contention without
losing observed performance. These runs still compare fresh full XML. Sub-second
push is not achieved, and changed-source import/compilation timing has not been
established by these no-change samples. A future fast change token must cover
application metadata, includes, component changes, additions, and deletions before
it can safely replace full exports.

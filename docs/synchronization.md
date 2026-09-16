# Synchronization status and safety gates

M2 is in progress. The CLI uses a shared three-way planner and a staged pull
executor. Push separates source verification from compilation and reconciles interrupted attempts before replanning.
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
Git with the rest of `.openroad`. A successful first application export (including
`--output`) or in-project component export records the configured target if there
was no cached baseline or tracked application inventory before the export. Failure
to query optional change metadata does not prevent this binding. Failed exports
do not create a binding; existing unbound caches still require verified `--bind`.
A new cache-free sync can also bind automatically;
a dry run never creates the binding. The target includes backend, executing host,
vnode, and database, without credentials. A changed configured target is rejected
by status/sync and the CLI export/import commands. Use a fresh checkout/cache for a
new target. This checks configured identity: it does not yet detect a server-side
vnode remapping or database replacement under the same name.

## Current execution policy

- Ordinary conflicts stop both directions before execution; explicit recovery can choose disk or database authority.
- Pull stops if disk has pending changes, even to unrelated components.
- Push stops if the database has pending changes, even to unrelated components.
- Pull supports database-side component and application deletions and application
  metadata changes. Unrelated files such as notes survive application deletion.
- Push still blocks pending deletions.
- Existing push metadata/type restrictions continue to apply.

Existing compact projects use baseline-preserving overlays for comparisons and
recovery verification. Standalone reconstruction is not an exact substitute for
that comparison: exported XML may contain opaque metadata and explicit defaults
that are intentionally absent from readable files.

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
and use an explicit authority choice to reconcile source/cache; do not manually remove the marker. A stale legacy `.openroad/pull.lock` likewise requires checking that no pull
process is still active before removal.

File replacement is atomic per file, not across the whole project. Revalidation is
optimistic: external Workbench/file writes can still race the final checks. CLI source commands within a project now share `.openroad/mutation.lock`, held
across planning, backend calls, and local installation. This includes sync/bind,
component import, app/component export, scaffolding, configuration, defaults
flattening, and encoding. An overlapping command fails immediately. The lock records
its process ID and operation; an ordinary exception releases it. New locks carry host/process/start-time ownership, allowing proven-dead local owners
to be reclaimed. Legacy or remote locks without provable ownership require inspection.
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

Before execution, push retains its plan, submitted XML, and cached baselines under
`.openroad/pushes/OPERATION`. A pending record describes an interrupted attempt;
normal sync reconciles recognizable database writes before replanning. It does not
require compilation to succeed. Independent database edits remain conflicts.

Post-import source verification or baseline installation failure requires explicit
recovery. `gorak recover push` verifies agreement without changing readable source;
`gorak recover push --take disk` and `--take database` choose authority for the
tracked project. `gorak sync --push --force` chooses disk and retains displaced
source and tracking. None bypass target identity, active writers, revision quarantine,
or source verification. See [push and recovery](push.md) for scope and examples.

Baselines and canonical WML are staged until source verification succeeds. An
interrupted installation remains a recovery condition because local tracking may
be partially installed. Source is durably verified before compilation is attempted;
compiler diagnostics and its retry queue are independent of source recovery.

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

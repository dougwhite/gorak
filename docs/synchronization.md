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

Older projects without source companions may report invalid/unsupported disk
projections. Reconcile edits and export applications to the current portable format
before using this workflow; do not assume a re-export preserves uncommitted edits.

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
optimistic: external Workbench/file writes can still race the final checks. The pull
lock serializes pulls only; do not run other modifying Gorak commands concurrently.
Direct calls to legacy Python orchestration functions bypass the CLI safety gates.
Shared locking across commands, stronger push validation, and database-side deletion
execution remain M2 work.

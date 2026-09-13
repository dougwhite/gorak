# Synchronization status and safety gates

M2 is in progress. The CLI now runs a shared three-way planner before sync, but
execution still uses the existing pull/push implementations. This is a conservative
safety layer, not completed bidirectional synchronization or transactional execution.

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

- Conflicts stop both directions before the existing executor runs.
- Pull stops if disk has pending changes, even to unrelated components.
- Push stops if the database has pending changes, even to unrelated components.
- Pending deletions are reported and blocked; no deletion executor exists yet.
- Pending application metadata pulls are blocked pending the new pull executor.
- Existing push metadata/type restrictions continue to apply.

Older projects without source companions may report invalid/unsupported disk
projections. Reconcile edits and export applications to the current portable format
before using this workflow; do not assume a re-export preserves uncommitted edits.

The guard is currently at the CLI boundary. Direct Python calls to the older
orchestration functions do not provide this new guard. Planning and execution are
not atomic: concurrent Workbench or file edits can still race the executor. M2 must
move snapshot validation, locking, baseline advancement, target verification, and
safe deletion into shared execution before claiming complete sync safety.

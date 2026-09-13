# Source change journal consumer prototype

After installing tracking, inspect committed events from a configured project:

```sh
gorak journal --limit 10
```

This requires ODBC and an installation readable by the configured account. It uses
explicit MVCC with shared read locking and a five-second lock timeout; it never
falls back to dirty reads. Each poll closes its database transaction so a later
poll can see newly committed changes. This command does not modify the source
database.

Output includes the installation UUID, up to the requested number of pending
events, and the number of journal rows scanned. Each event preserves its source
table, insert/update/delete action, and old/new identities, including names and
chunk keys where present. Events are candidates for source comparison; compilation
can also produce events. Referenced strings/images still need dependency resolution.

## Acknowledgments and failure behavior

Each checkout stores local consumer state in `.openroad/journal.sqlite3`.
The CLI holds the existing checkout mutation lock while accessing it. Previewing
creates/binds this local store but **does not acknowledge anything**. Repeated
previews will therefore show pending events again. The displayed limit bounds the
number of pending events returned, not total journal work.

The shared Python consumer service accepts a callback and acknowledges each exact
event ID only after that callback returns successfully. A future source processor
must durably persist its verified work before returning. It must also tolerate
replay: a crash or acknowledgment failure after completed work causes that event
to be processed again. Previously acknowledged events remain acknowledged if a
later callback fails. Callers must hold the checkout lock across processing.

Acknowledgments use SQLite transactions with FULL synchronous writes. They are
individual event IDs, never a highest-seen cursor. If transaction B commits event
3 before transaction A commits event 2, acknowledging 3 cannot hide 2 on the next
poll. Separate checkout stores track progress independently. No user-facing
acknowledge/discard command is provided.

An installation UUID change stops polling and requires a verified full rebootstrap.
Do not delete local state merely to suppress the error. A restored database that
retains its old UUID is not detected by this mechanism. Copied local caches also
copy acknowledgments; do not distribute `.openroad` with source checkouts.

## Scope and performance limits

This is a recoverable consumer primitive, not an incremental source implementation.
`status`, `sync`, and `test` are unchanged; `incremental_ready` remains false.

The first implementation streams retained journal metadata and filters acknowledged
IDs locally. It avoids downloading source payloads, but polling still scales with
journal history and performs a local lookup per scanned event. A no-change poll is
**not yet constant-cost**. Neither journal events nor acknowledgments are pruned.

Before enabling a fast source path we still need:

- A verified source-baseline bootstrap and durable source-processing callback.
- Complete hook/schema health and source-change coverage checks.
- Server-side pending-event selection and a safe retention/expiration protocol.
- Database restore detection beyond the installation UUID.
- Large-history and concurrent-save performance acceptance.

Automated tests cover lower-ID late arrival, independent consumers, preview
repetition, bounded batches, deletion identity, installation replacement, callback
failure, and acknowledgment failure. A read-only live poll of an installed demo
database verified the empty-journal path and repeat polling. Earlier
[transaction research](research/change-journal.md) proved rollback and reverse
commit behavior with actual Ingres sessions; the new consumer's populated-journal
path still needs live acceptance.

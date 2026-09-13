# Source change journal consumer

After installing tracking, inspect committed events from a configured project:

```sh
gorak journal --limit 10
```

This requires ODBC and an installation readable by the configured account. It uses
explicit MVCC with shared read locking and a five-second lock timeout; it never
falls back to dirty reads. Each poll closes its database transaction so a later
poll can see newly committed changes. This command does not modify source objects. On schema v2 it may publish
previously completed local acknowledgments to the tracking acknowledgment table.

Output includes the installation UUID, up to the requested number of pending
events, and `scanned_events`, the number of event rows fetched by the client.
That field does not measure rows examined internally by the database server. Each event preserves its source
table, insert/update/delete action, and old/new identities, including names and
chunk keys where present. Events are candidates for source comparison; compilation
can also produce events. Referenced strings/images still need dependency resolution.

## Acknowledgments and failure behavior

Each checkout stores local consumer state in `.openroad/journal.sqlite3`.
The CLI holds the existing checkout mutation lock while accessing it. Previewing
creates/binds this local store but **does not acknowledge newly previewed events**.
Schema v2 also gives the checkout a durable consumer UUID and publishes acknowledgments
for work that the processing callback previously completed. Repeated
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

Version 1 streams retained journal metadata and filters acknowledged IDs locally.
Version 2 performs a bounded `NOT EXISTS` query against
`gorak_journal_acks(consumer_id, event_id)` on the database server. Only pending
event rows are returned, up to the requested limit. An indexed primary key supports
acknowledgment lookup. A no-change poll transfers no event rows.

Local acknowledgments are durably queued in an indexed SQLite outbox. Publication
runs in batches of 256; only after the database commit succeeds does the client
record publication and remove the outbox entries. An uncertain commit resends the
same IDs idempotently. Existing local acknowledgments are queued once when first
using schema v2. A local source processor never acknowledges work merely by polling.

This bounds transferred event metadata, but does not prove constant-cost database
execution: the anti-join can still examine retained event history. Neither events
nor acknowledgments are pruned. Large-history query-plan and retention work remains.
Do not run older Gorak binaries against a consumer store after upgrading it.

Before enabling a fast source path we still need:

- A verified source-baseline bootstrap and durable source-processing callback.
- Complete hook/schema health and source-change coverage checks.
- Large-history query plans and a safe retention/expiration protocol.
- Database restore detection beyond the installation UUID.
- Large-history and concurrent-save performance acceptance.

Automated tests cover lower-ID late arrival, independent consumers, preview
repetition, bounded batches, deletion identity, installation replacement, callback
failure, and acknowledgment failure. A read-only live poll of an installed demo
database verified the empty-journal path and repeat polling. Earlier
[transaction research](research/change-journal.md) proved rollback and reverse
commit behavior with actual Ingres sessions; the v2 consumer now also has populated live acceptance using synthetic journal
events: lower-ID late arrival, independent checkouts, and zero event-row transfer
after all events were acknowledged. These injected events validate the consumer,
not broader source-hook coverage.

Ten empty polls over the two-event isolated fixture measured approximately 4.1 ms
minimum, 4.9 ms median, and 52.6 ms maximum within the Python process, including the
ODBC engine/connection path. This is a tiny-fixture measurement, not full CLI or
large-repository performance acceptance.

## Upgrade and privileges

Existing v1 installations continue to work using the previous reader. To enable
server-side selection:

```sh
gorak install --upgrade
gorak install --check
gorak journal --limit 10
```

The upgrade preserves the installation UUID and existing capture events/rules.
It adds one acknowledgment table and grants the configured ODBC account SELECT and
INSERT there. It grants no UPDATE/DELETE or source-write rights. Accounts sharing
that access are trusted collaborators: consumer UUIDs separate progress, not
authorization. Acknowledgments are not trusted evidence for deleting shared history.

The consumer still does not drive `status` or `sync`; verified source processing
and complete hook health remain prerequisites.

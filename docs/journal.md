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

## Reconcile events against source

```sh
gorak journal --reconcile --limit 100
```

This connects pending events to the existing full three-way source comparison.
It requires a verified sync target binding and a complete tracking inventory.
It supports either tracking schema version; v2 additionally publishes completed
acknowledgments on subsequent polls.

For a nonempty batch, Gorak captures fresh XML for every tracked/present project
application, compares disk and database against the common sync baseline, and
saves the comparison under `.openroad/journal-comparisons/<operation>/`.
The directory contains exported XML, its application map, and `comparison.json`.
One full comparison is shared by the batch. Events concerning applications outside
the checkout do not automatically add those applications to the project scope.

Events are acknowledged only if disk and database agree for the whole project
scope (unchanged or converged) and the source fingerprint remained stable through
comparison and evidence persistence. Pending pushes, pulls, conflicts, invalid source,
export failures, installation identity changes, or storage failures stop processing.
A difference report is retained where comparison completed, and events remain pending.

The XML and receipt are flushed before the event-to-report link is committed locally,
and that link is committed before acknowledging the exact event ID. Filesystem failure
before acknowledgment replays the comparison. A later batch uses fresh evidence rather
than trusting a previous receipt. POSIX directories are fsynced; directory fsync is
not available in this implementation on Windows, where only file flushes are explicit.

**This command neither imports source nor advances the common sync baseline.**
Those baselines must continue to preserve the last common disk/database version,
particularly during conflicts. Reconciliation evidence is a separate observation
snapshot, not a substitute baseline. Finish the appropriate sync or resolve differences
before retrying a blocked journal reconciliation. The command does not repair source.

An empty batch performs no XML comparison and reports `comparison: null`; that is
not a claim that the source is unchanged. Normal `status` and `sync` still perform
their full checks. Selective comparison/cache reuse needs complete invalidation,
source-to-app dependency mapping and verified bootstrap before it can be enabled.

Live isolated acceptance used a temporary checkout copy, fresh OpenROAD XML exports,
and one synthetic journal event. The command saved evidence and acknowledged the
event without changing source or common baselines; temporary tracking objects were
removed afterward. Tests additionally cover conflicts/pushes/pulls, concurrent disk
edits, durability failure, and replay after acknowledgment failure.

## Map events to application candidates

```sh
gorak journal --map --limit 100
```

This previews the selected batch with a `mapping` result:

- `applications`: the union of application names found, normalized to lower case.
- `full_comparison`: true if any selected event cannot be mapped completely.
- `events`: per-event candidate applications and fallback reasons.
- `metadata_queries`: number of batched entity lookups, excluding installation checks.

The mapper queries only identity, parent, base, name and type metadata through
ODBC. It follows version-to-base and component-to-application ancestry and keeps
historical edges from both sides of entity events. Moves and application renames
therefore retain both application candidates. Tombstones from other events in the
same batch can resolve an entity that has disappeared from the database. Includes
map to their declaring application; included-image build dependencies remain separate.

Shared strings, Unicode strings and images always request full comparison until
ownership/reference mapping is implemented. Missing ancestry, cycles, invalid names,
and traversal limits also request full comparison. Deleted component/application/
encoded rows require captured historical identity evidence; a current row alone
cannot prove that an ID was not reused. A bounded batch may omit the needed tombstone,
so fallback is expected even when a later batch could explain the deletion.

Lookups are parameterized, deduplicated and batched in groups of 128 IDs, with a
16-level and 10,000-identity bound. The reader uses explicit MVCC/shared read locking
and checks the installation UUID before and after traversal. Installation mismatch or
database errors fail the command; they are not treated as an empty candidate set.

Mapping does not acknowledge newly previewed events, import source, update common
baselines, or change the scope of status/sync/reconciliation. As with normal preview,
previously completed acknowledgment publication may occur during polling. Mapping and
reconciliation flags are separate modes.

`full_comparison: false` means only that the selected events were resolved by this
mapper. It does not certify journal coverage, a complete transaction/batch, absence of
other changes, or permission to reuse cached source. Historical ID reuse and concurrent
metadata movement still need broader acceptance before cache reuse. Unknown events
must never be silently discarded when this service is integrated into comparison.

Tests cover moves, renames, deleted graphs, missing history, shared storage, cycles,
traversal limits, batched ancestry and installation replacement. A synthetic script
edit's candidates were checked against the full three-way planner. Read-only live
acceptance mapped 30 actual demo component identities to the applications reported
by the existing metadata reader using two batched entity queries. Live Workbench
rename/move/delete and shared-storage reference coverage remain open.

## Verify selective snapshot refresh

```sh
gorak journal --verify-selective --limit 100
```

This mode exercises selective application refresh while retaining a mandatory
fresh full-export reference. It requires the same verified target binding and
tracking inventory as reconciliation. It is separate from `--map` and `--reconcile`.

The first run bootstraps a full observation snapshot. Subsequent runs can copy
unchanged application XML from that snapshot and export mapped applications.
The live application inventory is still read, so newly available applications
within project scope are exported and deleted applications are omitted.

Every selective pass is compared semantically with fresh full exports. A missing,
corrupt, mismatched-target, changed-installation, or changed-scope snapshot causes
full fallback. Unresolved event mapping also causes full fallback. If the selective
snapshot differs from the reference—whether because of an omitted event, a bounded
batch, or a concurrent database change—the full reference is retained and the
mismatch is reported.

Output includes `mode` (`selective_verified` or `full_fallback`), the fallback
reason, reused and selectively exported application names, the full-reference
application list, and the existing three-way source differences. General reconciliation acknowledgments are unchanged. A private observer
checkpoints the inspected event IDs only alongside a successful full-reference
snapshot; its publication protocol is described below.

Evidence is stored in `.openroad/journal-snapshots/<operation>/`. A local
`.openroad/journal-snapshot.json` pointer records installation identity, configured
target, project scope and SHA-256 hashes of the full-reference XML. Cache paths and
hashes are checked before reuse. The full-reference evidence is flushed before
atomic pointer replacement. Source drift or an export/evidence failure before
publication leaves the previous pointer intact. Old evidence is retained; automatic
artifact retention is not implemented.

Snapshots may record pending pushes, pulls or conflicts. They describe observed
database source and **never replace common sync baselines or disk source**.
Normal status, sync and reconciliation still use full comparisons.

This mode is a validation tool, not the final fast path. It can do more work than
normal status because it performs both selective and full-reference comparisons.
A quiet journal and `selective_verified` do not certify future hook coverage.
Removing the reference check requires complete invalidation/health and snapshot
continuity acceptance.

Live isolated acceptance bootstrapped four applications, reused all four during
an empty-event selective pass, then refreshed one mapped application while reusing
three. Both selective passes matched fresh full exports. The checkout was temporary
and test tracking objects were removed. Tests additionally verify that an omitted
event causes a mismatch/fallback, remote deletion drops cached inventory, damaged
cache falls back, and export/durability/concurrent-source failures prevent publication.

### Observation-window guard

Selective verification now reads the committed journal count and maximum event ID
before polling and again immediately before publishing its snapshot pointer.
Each read uses a fresh ODBC connection and one aggregate statement containing the
installation marker. A change in identity, schema version, count or maximum rejects
publication and preserves the previous pointer. Connection failure also aborts
publication. No new general-consumer events are acknowledged; private observer
progress is published with successful snapshot evidence.

This uses the entire retained journal, independent of consumer acknowledgments.
A count increase detects a lower event ID that commits late even when the maximum
does not change. The aggregate may scan retained history: it is a diagnostic guard,
not the intended scalable no-change query or a high-watermark cursor.

Selective verification now reads at most one extra pending event to test whether
the query is exhausted. More events than the 100,000-event observation budget use full fallback
with reason event_batch_at_limit; the lookahead event is not processed or
acknowledged. An exactly-budget window can proceed only when exhaustion is established.
Unknown completeness retains the previous conservative fallback. Transactions
spanning a truncated window still cannot justify selective reuse.

Reports and pointers record journal_observation. Reports explicitly retain
continuity_certified=false and incremental_ready=false. The mandatory full XML
reference remains.

An unchanged count/maximum does not detect a restore retaining the same installation
UUID and aggregate values, delete-and-reinsert replacement of history, disabled
hooks, or source changes outside hook coverage. Nor does it provide an atomic
cross-application export: a commit can occur after the final observation. Snapshots
remain observations requiring a fresh full reference on the next verification.
These guards must not be used to authorize fast status/sync or event pruning.

The aggregate query was verified read-only against a live schema-v2 installation
with an empty journal (about 0.047 seconds for connection plus query in one run).
A later [live acceptance probe](research/journal-recovery-acceptance.md) verified
a lower-ID transaction committing during export. Populated-history scale, physical
restores and broader reconnect acceptance remain unmeasured. Automated regressions cover late lower-ID commits,
higher-ID commits, shrinking history, changed installation identity, a final-read
disconnect and a full event batch; failure cases preserve the old pointer.

### Restore and local rebootstrap

After a known database restore/replacement, or when the journal reports a changed
installation identity, use:

```sh
gorak install --check
gorak journal --rebootstrap
```

Run this for **each affected checkout**, with source writers paused for the recovery
comparison. Repair an incomplete tracking installation through the DBA first.
Rebootstrap requires a healthy installation and an already verified source target
binding; it does not authorize switching to a different server/database.

Rebootstrap ignores previous observed XML and stages a new SQLite consumer with a
new consumer UUID, no acknowledgments and the current installation identity. It
performs full source exports and applies the same disk/installation/journal-window
checks as selective verification. Differences and conflicts may be reported: this
is an observation rebuild, not source reconciliation.

On successful verification, it archives the old SQLite state and snapshot pointer
under the operation's previous directory. It invalidates the old pointer, replaces
the consumer, then publishes the new full-reference pointer. Exports and evidence
failures before publication leave current state unchanged. An interruption during
replacement can leave no pointer; retry rebootstrap after resolving the failure.
Old XML evidence is retained. Do not restore an archived consumer after a database
restore merely to suppress replay.

No source files, common sync baselines, server tracking objects or server
acknowledgments are reset. The fresh consumer sees all retained events again,
including IDs previously acknowledged by this checkout. Other checkouts are
unchanged. There is no automatic cleanup of old server consumer acknowledgments.
SQLite sidecars block replacement; close other users and inspect recovery needs.
A corrupt SQLite database that cannot be archived also requires manual inspection.

A restore that retains the same installation UUID may not be detected automatically.
The DBA/operator must notify checkout users to rebootstrap even if install --check
passes. Rebootstrap does not create a database-wide restore generation, prove that
all historical events survived, or enable incremental status. Coordinated restore
generation and broader continuity acceptance remain future work.

Automated acceptance covers a changed local binding, fresh consumer identity,
archived acknowledgments, unchanged common baselines, export failure, interruption
during consumer replacement, sidecar rejection and CLI mode exclusivity. Live acceptance also verified replay after same-identity rebootstrap, rejection of
a changed identity, and successful recovery and subsequent verification. See
[recovery acceptance](research/journal-recovery-acceptance.md). No physical database
restore has yet been exercised.

### Historical entity ancestry in diagnostic snapshots

Observation pointers include a hash-checked ancestry.json beside the full XML
reference. It records entity IDs, parent/base links, names and kinds from a bounded
ODBC metadata read inside the same guarded observation window. It does not change
the database tracking schema. Older pointer formats automatically take the full
bootstrap path.

The next selective verification gives the mapper this historical graph in addition
to event tombstones and current database metadata. A deleted component/include ID
can avoid fallback only when its previous ancestry resolves completely without
using current rows to fill historical gaps. Historical and current application
candidates are retained together, including when an ID now belongs to a different
application. Shared storage still requires full comparison.

A plain journal --map call has no snapshot context and retains its conservative
behavior. Corrupt ancestry invalidates the entire observed snapshot. Rebootstrap
never imports old ancestry. Evidence is flushed before the pointer is published;
a metadata-read failure preserves the prior pointer.

This prototype captures at most 100,000 entity rows across the source database.
The SQL caps the result at that limit plus one. Exceeding the budget records no
historical graph and preserves the existing full-reference behavior. No source
payload is read by the ancestry query. Scoped/indexed ancestry and large-corpus
cost remain future work; this scan is not the proposed final no-change path.

A historical observation is not an event-time ownership certificate: incomplete
batches, prior acknowledgments, intervening identity histories and restore
continuity still need the wider consumer protocol. The full-export oracle and
continuity_certified=false remain mandatory.

Live isolated acceptance created a separate fixture application and bootstrapped a
snapshot. Explicit compilation generated 77 events; deleting its include relationship
generated one event. Both batches required fallback without history, resolved with
the previous snapshot graph, and matched fresh full references. Compilation and
direct SQL include deletion were used to exercise these histories autonomously;
this was not another human Workbench save. The extra test application was removed;
the existing Workbench acceptance app and tracking installation were preserved.


### Bounded pending-set completeness

The snapshot report includes pending_set_complete, measured at the event query.
Schema v2 applies FIRST 100001 server-side for this diagnostic. The --limit
argument controls fetch chunk size (capped at 256 rows per fetch); ordinary preview
and consumer polling retain their existing event limit. Schema v1 can still scan
acknowledged history locally. Observations retain at most 100,000 events and
acknowledge none as a consequence of lookahead. Invalid lookahead data fails the
read rather than being silently ignored.

A complete query is not a transaction cursor or a guarantee about future commits.
The before/after journal observation, full-reference comparison and conservative
mapping guards remain. One query cursor supplies all chunks without intermediate acknowledgments, offsets
or sequence watermarks. Larger sets still fall back. This bounds returned event
memory, not total SQL work, retained history or mapping cost.

Before multi-chunk windows were introduced, live read-only acceptance used 447 retained events and a fresh temporary consumer.
A limit of 447 reported complete; 446 reported incomplete and transferred only the
one additional event needed to establish it. The journal stayed unchanged and no
events were acknowledged.


### Private observer checkpoints

Snapshot pointer format 3 binds full XML, ancestry and an observer.sqlite3 progress
file through hashes and one atomic pointer replacement. Routine verification no
longer reads or advances the general journal.sqlite3 consumer used by preview and
reconciliation. General acknowledgments cannot hide events from the observer.

Each operation stages a copy of the previous observer database (or creates a new
consumer on bootstrap). Polling that copy can publish previously verified outbox
entries. After the full reference and stability checks, it records only the returned
event IDs in the staged observer's acknowledgments and outbox. The lookahead event
remains pending. XML, ancestry, SQLite state and report are flushed before pointer
publication. A later operation publishes those new observer IDs to the server only
after loading the successful checkpoint.

An unpublished operation's new progress is never used for subsequent polling. A
failed reference, metadata read, receipt flush or publication preserves the previous
published observation (or leaves no pointer during explicit rebootstrap recovery).
The previous observer database is never opened for mutation.

Reports retain acknowledged=false for general reconciliation and add
observer_consumer_id, observer_checkpointed_events and general_consumer_unchanged.
These private acknowledgments mean "included in a full observed comparison", not
"disk and database agree" or "imported". Differences/conflicts may remain in the
report; common source baselines never advance.

Rebootstrap resets the general consumer as before and independently creates a fresh
observer. Older format-1/2 pointers rebuild through a full reference and a new
observer, replaying retained events. Missing or corrupted observer files invalidate
the entire snapshot. Old observer/server acknowledgment retention is not implemented.

Live isolated acceptance acknowledged real compile and include-delete events through
the general consumer before verification. The private observer still saw all 77
compile events and the include deletion, and both selective passes matched full
references. A following quiet pass checkpointed zero new events. The temporary app
was removed and existing manual acceptance tracking was retained.

This is still a diagnostic protocol. Receipt consistency is checked as described
below, but deliberate local/database restores still require rebootstrap. Physical
restore detection, complete larger event windows, retention, scalable receipt
validation and removal of the full oracle remain open. Do not use these checkpoints
to authorize incremental status/sync yet.


### Observer receipt consistency

Before publishing an observer outbox on schema v2, verification streams the server's
receipt IDs and checks them against the staged local acknowledgment database:

- Every server receipt must be locally acknowledged.
- Every locally published receipt must still exist on the server.
- A server receipt still in the local outbox is allowed, covering a server commit
  whose success was not recorded locally.

The check compares IDs, not just totals. Equal-sized but different histories are
rejected. Divergence stops before event processing and directs the operator to
journal --rebootstrap. It never deletes or fabricates receipts to make them agree.

This detects an older local checkpoint after a newer checkpoint published receipts,
and server receipt loss relative to known local publication. It does not detect a
restore that preserves those exact receipts while replacing source/journal data.
General consumer polling is unchanged; this check is specific to the private
observer. Schema v1 has no server receipt table and retains full-reference-only
diagnostic behavior.

The query streams bounded fetch chunks but examines all retained receipts for this
consumer. It is deliberately O(history) and is not suitable as the final large-repo
fast-path check. A compact, transaction-safe generation/checkpoint protocol remains
a prerequisite to replacing this diagnostic guard.

Live acceptance used a temporary private consumer over retained isolated events.
It rejected an old observer after newer receipts had been published, then rejected
the newer observer after its server receipts were removed. Only that test consumer's
receipt rows were deleted; source and other consumers were unchanged. Regression
tests additionally cover same-count/different-ID history and uncertain commits.


### Multi-chunk observation windows

A snapshot observation can now collect more pending events than --limit in one
cursor, up to the fixed 100,000-event budget plus one lookahead. All returned
chunks are mapped together. No newly read IDs enter either local acknowledgments
or server receipts during collection. Only the successfully verified full
reference can publish the staged observer checkpoint. An invalid later chunk or
failed publication leaves earlier chunks replayable. Reports include
pending_event_budget and pending_fetch_size; the existing event_batch_at_limit
fallback name is retained for an exhausted budget.

Automated server-boundary tests cover multiple chunks, exact/overflow budgets,
later-chunk invalid data, and a lower ID arriving after checkpoint publication.
The snapshot failure test spans multiple chunks and verifies replay with the old
pointer unchanged and no new server receipts. These tests use a SQLite SQL adapter;
live Ingres multi-chunk acceptance subsequently passed against 704 retained events.
See [live results](research/revision-token-acceptance.md). Large-corpus measurements
remain pending.

See [checkpoint protocol requirements](research/checkpoint-protocol.md) for the
next infrastructure gate. Normal status and sync still use their existing paths.

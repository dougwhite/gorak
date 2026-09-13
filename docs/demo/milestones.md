# Delivery milestones and gap ledger

Updated 2026-09-13 after source-storage and development-loop research. This is the
implementation backlog, not a claim that the proposed commands exist. Preserve
existing IDs for earlier evidence; M2 is now split into explicit work packages.
Implementation, automated validation, live acceptance, and presenter acceptance
are separate gates.

## Target and evidence

ODBC is the accepted required source-access transport for the target stack. Local
Windows or SSH OpenROAD execution remains for running, testing, image builds, and
explicit compilation. The normal source path should eventually avoid XML and
OpenROAD process startup; XML remains the compatibility oracle/fallback during
transition. Direct decoding and safe database saves are not yet implemented.

Design for gigabytes of source, not only the demonstration corpus. A no-change
status/push should target under one second without work proportional to total
source bytes. Measure cold/warm runs, changed-object latency, test latency, build
latency, and save overhead separately; one fast sample is not acceptance.

Research evidence: [encoded storage and compilation](../research/encoded-source.md)
and [sync behavior and timing](../synchronization.md).

- Direct demo read: 140 encoded chunks, about 211k characters, approximately 3 ms
  after a 31 ms ODBC connection.
- Larger seven-app corpus: about 124.5 MB, 1.07 s fetch plus 0.24 s local hashing.
  Fetching/hashing all source on every command does not scale.
- Full-export no-change path improved to about 2.1 s in one sample using concurrent
  exports and SSH reuse; another status sample took 5.1 s. VM load matters.
- Import without `-f` and subsequent run succeeded for a disposable procedure.
  Explicit compilation changed encoded bytes and change counters without a source
  edit. Raw fingerprint changes require semantic comparison, not automatic conflict.
- Current test path has separate upload and SSH/PowerShell/OpenROAD overhead and
  bypasses source transport's SSH reuse. Runtime/compile startup needs separate timing.

## Milestone map

| ID | Milestone | State | Acceptance gate |
| --- | --- | --- | --- |
| M0 | Preserve baseline and document demo | Complete; roadmap updated | Walkthrough, decisions, gaps, and evidence retained |
| M1 | Portable source and fresh-clone reconstruction | Representative CLI and owner visual acceptance passed | Cache-free clone restores equivalent source and runnable sample; broader types remain open |
| M2a | Complete sync correctness and recovery | Substantial partial implementation | Both directions handle edits/additions/deletions; conflicts, branch switches, interruptions preserve work |
| M2b | Install database change tracking | DBA SQL export implemented; capture-only, consumer/broad coverage pending | Transaction-safe journal covers all source changes with bounded save overhead |
| M2c | Incremental ODBC status and fingerprinting | Research | Sub-second no-change target on a large corpus; no full-source fetch; trustworthy invalidation |
| M2d | Direct source decoding | Research | ODBC → Gorak source matches reference exports across supported types without w4gldev |
| M2e | Direct source encoding and saving | Not started | Disk → DB → Workbench/run round trip preserves source and repository invariants |
| M3 | ODBC onboarding and source dependency export | Partial existing configuration | Diagnosed install/setup and multiple-app export with include closure |
| M4 | Locked Git dependencies | Not started | Clean checkout restores exact dependency revisions without discarding local edits |
| M5 | Fast test-driven editor loop | Partial runner/scaffolding | Saved edit → sync → red/green tests with reliable compilation diagnostics |
| M6 | Full and incremental image builds | Run support only | Only necessary images rebuild, including correct dependency invalidation |
| M7 | Editor tasks and community rehearsal | Not started | Two developers complete Acts 1–5 from clean disposable environments |
| M8 | Watch, rich editor tests, and MCP | Not started | Same safe services power automatic sync and agent/editor tooling |

Recommended order: finish bounded M2a gaps alongside M2b research, then M2c, M2d,
M2e; integrate M3 onboarding with the database installer. M5 transport and deferred
compilation work can proceed independently. M4 and M6 follow the stable source/app
model. M7 rehearses the integrated result; M8 builds on it.

## M1: Portable source compatibility

- [x] Preserve unrepresented XML as tracked source companions, separate from caches.
- [x] Define readable-field ownership; preserve opaque content and script whitespace.
- [x] Restore a representative fresh clone into an empty target; owner viewed frames.
- [x] Compare older exports using cached XML without treating them as new components.
- [ ] Version the source format and provide explicit migration/compatibility policy.
- [ ] Broaden acceptance for images, complex frames, events, Unicode, all component
  kinds, application metadata, and includes; do not infer this from the sample.
- [ ] Evolve preserved companions as direct decoding matures without losing source.

## M2a: Sync correctness and recovery

Implemented slices include a shared three-way planner, configured-target binding,
CLI checkout locking, staged pulls including database-side deletion, staged push
baselines, retained recovery evidence, and verified `gorak recover push` when disk
and database agree. These do not constitute database transactions across commands.

- [ ] Disk-side component/application deletion with tombstones and delete/edit checks.
- [ ] Explicit reconciliation workflow for partial writes and divergent source.
- [ ] Pull recovery command; stale-lock diagnosis without unsafe automatic removal.
- [ ] Branch switches, renamed/case-colliding objects, cloned caches, replaced databases.
- [ ] Strengthen identity beyond configured connection strings (database generation).
- [ ] Preserve optimistic drift checks and fail closed while replacing transports.

## M2b: Versioned database installer and journal

`gorak install --export-sql PATH` now exports a DBA-applied capture-only hook script.
Direct installation now uses the configured execution backend with ODBC verification.
A replayable local-acknowledgment consumer and journal preview are implemented;
v2 adds server-side pending selection and durable acknowledgment publication.
Full-comparison journal reconciliation now persists observation snapshots before
acknowledgment. Selective source processing, large-history performance, and retention
remain pending. This capability
is accepted in principle; exact schema, syntax, privileges, and installation targets
must be explicit. Temporary rules and the generated script were validated in an isolated database
and removed afterward. See [DBA installation](../installation.md).

- [x] Temporary real source-table rules captured simple import, compile, include/metadata
  replacement and deletion; removed after testing. Privileged owner bootstrap required.
  See [source-rule coverage](../research/source-rule-coverage.md).
- [ ] Complete inventory of source-related tables and transaction/save behavior through controlled
  probes: script, metadata, include, frame, image, rename, version, deletion, no-op save.
- [ ] Minimal rule work: mark dirty identities or record small events, not repeatedly
  hash/rebuild an entire object on every chunk update.
- [x] Synthetic rule prototype: rollback, reverse commit, MVCC committed reads,
  independent consumers, updates and deletion events. See [journal research](../research/change-journal.md).
- [ ] Production cursor/retention and real-source transaction acceptance; sequence allocation alone is not a safe
  committed-change cursor. Choose and prove a correct watermark/acknowledgment model.
- [x] Consumer primitive: per-checkout durable event acknowledgments, callback-before-ack replay, installation UUID binding, and read-only journal preview. See [journal consumer](../journal.md).
- [ ] Integrate tombstones/source processing, retention, reconnect/offline consumers, and verified rescan bootstrap.
- [x] Read-only ODBC installation inventory check: owner objects, rule targets, version, UUID, event read access.
- [x] Compare catalog rule/procedure definitions with generated SQL; live altered-rule detection and restoration verified.
- [x] Real synthetic-app create/edit/compile/include/delete capture and bounded capture-failure acceptance. See [change acceptance](../research/journal-change-acceptance.md).
- [x] Validate tracking column names/order, datatypes, widths, scale and nullability; live narrowed-event-ID catalog probe rejected.
- [ ] Verify keys/indexes, sequence configuration, broader hook execution and database restore/replacement; definition/column checks alone are insufficient.
- [ ] Transactional installation where supported; schema version, check, upgrade, and
  removal procedures that preserve source and define tracking-data consequences.
- [ ] Measure rule overhead during large saves/imports/compilation and concurrent edits.

## M2c: Incremental ODBC and server-side fingerprints

- [x] Schema v2 selects only unacknowledged event rows server-side, with bounded returned batches.
- [ ] One small no-change query at scale; candidate-only payload reads for changed objects.
- [ ] Verify Ingres hash functions, input limits, Unicode/binary handling, and collision
  policy. Hash ordered, length-delimited complete values; never truncate or hash only
  lengths/timestamps. Prefer post-commit dirty-object hashing over row-trigger hashing.
- [x] Diagnostic event-to-application mapping follows current and historical parent/base relationships; uncertain/deleted/shared-storage cases request full comparison.
- [x] Isolated complex-frame replacement, label edit, long script, embedded-image removal and deletion map to the affected app. See [frame acceptance](../research/frame-journal-acceptance.md).
- [x] Live runtime StringObject/BitmapObject insert/update/delete capture, including explicit nstring storage, retains shared-ownership full fallback. See [API acceptance](../research/shared-storage-api-acceptance.md).
- [x] Live Workbench procedure/frame saves, component rename/delete, numbered version, description and include removal detected. Frame saves and include removal currently require full fallback. See [Workbench acceptance](../research/workbench-journal-acceptance.md).
- [ ] Complete shared-storage ownership, cross-app moves, version restore/purge and broader save coverage before selective cache reuse.
- [ ] Associate fingerprints with verified semantic baselines and database identity.
- [ ] Treat compile-only byte changes as candidates for comparison, not source edits.
- [x] Journal reconciliation persists full XML comparison evidence before exact-event acknowledgment, with disk-drift checks; common sync baselines remain unchanged.
- [x] Selective observation refresh verified against mandatory full exports; corruption/unresolved mapping/mismatch use full fallback. Separate snapshots preserve common baselines.
- [x] Guard diagnostic snapshot publication with before/after committed journal observations; full event batches disable reuse. Regression coverage includes late commits, identity changes and disconnects.
- [x] Explicit local journal rebootstrap archives old state, creates a fresh consumer and verifies full exports without resetting source baselines. Restore notification remains an operator responsibility.
- [x] Isolated live acceptance: same-identity acknowledgment replay, changed-identity recovery, and rejection of a late lower-ID commit during export. See [recovery acceptance](../research/journal-recovery-acceptance.md).
- [x] Hash-checked historical entity ancestry narrows diagnostic deletion mapping while retaining current candidates; live compile/include checks match full exports. Plain journal mapping and full-reference guards remain conservative.
- [x] Bounded lookahead distinguishes an exhausted pending set from a truncated batch, without acknowledging the extra event; live exact/short-limit checks passed.
- [x] Private observer progress is hash-bound and atomically published with full-reference snapshots; general reconciliation cannot hide observer events. Unpublished checkpoints replay, with live independent-consumer acceptance.
- [x] Exact private-observer receipt checks detect older local checkpoints and lost server receipts, preserving uncertain-commit retries. Live isolated fault checks passed; this O(history) diagnostic still needs a scalable replacement.
- [x] Collect bounded multi-chunk pending windows without intermediate acknowledgments; automated later-chunk failure, publication replay and late lower-ID coverage. Live multi-chunk acceptance passed against 704 retained events; scale acceptance pending.
- [x] Isolated revision-token experiments establish transactional rollback/visibility but reject global writer contention and source-partition lock cycles; see [results](../research/revision-token-acceptance.md).
- [x] Isolated writer-session counters pass MVCC concurrency, rollback and observed identity reuse; page locks still contend and online consolidation rejects a racing writer. See [session results](../research/session-revision-acceptance.md).
- [ ] Establish Workbench/import/compiler writer lock configuration before enabling revision counters; initial bounded reads must fall back safely without online counter deletion.
- [ ] Implement and validate the [compact checkpoint protocol](../research/checkpoint-protocol.md), including transaction closure and restore/retention contracts.
- [ ] Certify snapshot continuity and invalidation before permitting selective status/sync without the full-export reference. Same-identity restore detection and atomic export boundaries remain unresolved.
- [ ] Large-corpus benchmark with cold/warm and tail latency; count queries, transferred
  bytes, memory, and server load. Sub-second is a target, not an achieved guarantee.
- [ ] Keep a verified full-rescan/reconciliation path when tracking is unavailable.

## M2d: Direct decoder

- [ ] Specify chunk assembly, string lengths/encodings, nulls, IDs/references, class
  layouts, version markers, and corruption handling for `ii_srcobj_encoded`.
- [ ] Start with procedures; then classes/globals, remaining declarations and app metadata.
- [ ] Resolve external strings, Unicode, images, nested fields, scripts and frame graphs.
- [ ] Separate source meaning from compiled IL and destination-local identifiers.
- [ ] Validate against XML and Workbench using synthetic fixtures plus a private larger
  corpus. Keep customer extracts and machine identifiers out of tracked artifacts.
- [ ] Fall back or fail explicitly on unknown encodings; never silently discard fields.

## M2e: Direct encoder and save protocol

- [ ] Specify more than serialization: entity/version allocation, component/app rows,
  includes, dependencies, locks, source relationships, and compilation invalidation.
- [ ] Transactional create/update/delete with concurrency checks and rollback tests.
- [ ] Prove Workbench can open, edit, save, run, and compile the resulting components.
- [ ] Verify no-op saves, change-journal integration, identity/version handling and repair.
- [ ] Broaden from simple procedures to the full corpus before retiring XML import.
- [ ] Retain recoverable artifacts and an explicit supported-version matrix.

## M3–M4: Configuration and dependencies

- [ ] Require and diagnose ODBC for source operations; document migration from existing
  local/remote SQL modes. Retain Windows-local and SSH execution transports.
- [ ] Coordinate project bootstrap, database initialization, tracking installation,
  runtime configuration, and helper installation without ambiguous command meanings.
- [ ] Multiple-app export and include closure; report external image requirements.
- [ ] Separate Git dependency declarations from OpenROAD application include lists.
- [ ] Ignored deterministic materialization directory, tracked exact-commit lock,
  explicit install/update, SSH Git URLs, app-name collisions, local-edit protection.
- [ ] No implicit execution of dependency hooks; clean-clone reproducibility.

## M5: Test-driven development loop

- [x] CLI run/test with SSH execution, XML reports, empty test app registration,
  and a manually authored intentional-failure loop.
- [ ] Unify runner SSH reuse; measure request transport, PowerShell, OpenROAD startup,
  compilation, test work, and result collection separately.
- [ ] Explicit deferred-compilation mode; distinguish source import success from compile
  success. Test whether unused invalid components are diagnosed; do not assume suite
  execution compiles everything. Preserve optional force-compile behavior.
- [ ] Framework-aware app/runner/test scaffolding and defined discovery/registration.
- [ ] Sync-before-test orchestration; sync failures stop the run, compile failures stop
  or fail execution clearly, stale reports never count as success.
- [ ] Stable machine-readable diagnostics with source paths/lines; malformed/missing
  reports, timeouts, skipped tests, and cleanup acceptance across execution transports.

## M6: Builds

- [ ] Full image build, configurable output, compiler diagnostics and artifact manifest.
- [ ] Included-image graph and dependency-ordered builds.
- [ ] Incremental keys include source, compiler/version, flags, config, included
  interfaces/artifacts, and external images. Verify correct transitive invalidation.
- [ ] Headless component execution versus visible Windows GUI launch acceptance.

## M7–M8: Demo, editor, watch, and MCP

- [ ] VS Code keybindings/tasks and navigable test/build diagnostics.
- [ ] Two-developer rehearsal, resettable fixtures, fresh clone, branch switch,
  frame design, conflict/deletion recovery, red-to-green tests, incremental builds.
- [ ] Record measured loop latency and actual human intervention for AI feature work.
- [ ] Watch debounce, atomic saves, restart safety, bounded retries, no feedback loops.
- [ ] Rich editor test discovery and navigation.
- [ ] Repository-scoped MCP server using the same source/planning/execution services:
  discovery/read/status first, then explicit safe mutations/run/test/build; respect
  target binding, locks, conflict/recovery state, diagnostics, and operation limits.
- [ ] Watch and MCP are later stack capabilities, not gates for recording Acts 1–5.

## Cross-cutting maintenance

Keep source representation, storage, planning, execution, transport, and reporting
separate. Prefer one business implementation over transport-specific feature copies.
Retain meaningful regression tests, synthetic fixtures, and sanitized documentation
and commit messages. Automated tests must not contact developer services. Existing
XML helpers remain supported until an explicitly validated replacement exists.
Maintain the original walkthrough and historical acceptance evidence; new design
choices must not retroactively imply prior verification or erase unresolved bugs.

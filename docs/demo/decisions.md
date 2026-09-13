# Architecture and delivery decisions

Accepted direction, 2026-09-13. Exact new CLI syntax and directory names remain
implementation decisions until documented and tested.

## Source and database roles

Git carries portable application source. Each developer or build worker has an
independent source database. Workbench remains supported for frame design and
source edits; synchronization is explicit before automation is added.

Readable source is preferred. Preserved XML companions may carry unrepresented
source structures so a fresh clone does not depend on an ignored export cache.
They are source artifacts, distinct from target-bound baselines and recovery logs.
The first implementation must specify ownership of duplicate represented fields
and reject ambiguity. Complete serialization of every OpenROAD structure is not a
prerequisite for preserving those structures faithfully.

Updated direction: ODBC becomes required for source access. Direct database decoding
and eventually encoding should remove OpenROAD/XML startup from the routine source
loop. XML remains a reference and fallback during migration. Direct reads are proven
fast on the small sample; complete decoding and safe repository writes are unproven.
See [storage research](../research/encoded-source.md).

## Two dependency relationships

A Git dependency supplies one or more Gorak applications. An OpenROAD application's
`included_applications` determines its compile/runtime include graph. Installing a
repository does not automatically include its applications everywhere.

Use a node_modules-like model: tracked dependency declarations and lock file,
ignored deterministic materialization directory, and explicit install/update
commands. Resolve immutable Git commits in the lock. Support SSH URLs. Do not
silently track a moving branch, overwrite locally edited installed source, or run
repository-provided hooks. Resolve application-name collisions explicitly.

The lock identifies the repository, revision, supplied apps, and source-format
compatibility. App includes continue to distinguish source apps from image files.
Dependency layout and manifest schema are finalized under M4, not invented as
already-supported fields in current projects.

## Synchronization

Compare a saved successful baseline, current disk content, and current database
content. Timestamps may accelerate discovery but cannot resolve conflicts.
Deletions require inventories/tombstones and explicit conflict rules. Target
identity is part of baseline validity.

Superseding the initial no-rules assumption: database rules and Gorak-owned tables
are now an accepted part of the proposed stack. A versioned `gorak install` should
provision tracking explicitly. Design for gigabytes of source: record small dirty
object/events transactionally and query incrementally. Prove rollback, out-of-order
commit, deletion, multi-checkout retention, and replacement/missing-rule handling.
Do not use allocated sequence numbers as commit-order cursors without proof.

Server-side hashing is a proposed optimization, subject to Ingres capability and
correctness checks. Avoid hashing an entire object on every chunk mutation. Include
all source metadata and referenced storage. Compilation changes raw encoded bytes;
hash differences trigger semantic comparison rather than declaring source conflict.
Target under one second for no-change status/push without scanning all source bytes;
measure changed pushes and test/build execution separately.

Planning is read-only. Pull, push, status, test orchestration, and watch consume the
same planner. Operations retain evidence and verify results before advancing state.
Cross-application atomicity is not assumed; partial completion is reported.

## Backends

Execution remains local Windows or SSH Windows. Existing source discovery supports
local SQL, remote SQL, and ODBC; the accepted target is mandatory ODBC source access,
with a documented transition rather than immediate removal of working backends.
Running/testing/building/explicit compilation still uses OpenROAD execution. Real
SSH acceptance does not prove local Windows or ODBC acceptance.

Import without forced compilation is documented and worked for a disposable probe.
Design an explicit deferred-compilation mode; verify run/test behavior for invalid
and unused components before assuming tests provide complete compiler coverage.
Direct saves require proof of repository/version/dependency/lock invariants as well
as an encoder; do not treat observed serialization as a supported write contract.
GUI execution in an interactive Windows session is a separate capability from
headless execution over SSH.

## Autonomous delivery

The owner has authorized implementation toward the documented demo, testing, and
focused Git commits and GitHub pushes. Continue routine design and implementation without asking for
approval at each step. Preserve unrelated working changes. Use the demo environment
and explicitly disposable targets for live mutations; do not repurpose unrelated
source repositories or shared databases for destructive acceptance tests.

Ask for help when credentials/access are unavailable, a decision materially changes
the agreed goal, or Workbench interaction needs a human. Recurring background scheduling remains a separate action, not implied by active
implementation or permission to publish commits.
No automatic scheduler is configured by this document. Work only runs while the
agent task is active or an explicitly configured automation is executing.

Every milestone records implementation, automated checks, live checks, limitations,
and outstanding manual acceptance. Make no claim of visual acceptance from XML
comparison alone. Keep local connection details out of committed records.

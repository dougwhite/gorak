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
identity is part of baseline validity. Database rules/private tracking tables are
not an initial requirement; revisit them only for demonstrated limitations.

Planning is read-only. Pull, push, status, test orchestration, and watch consume the
same planner. Operations retain evidence and verify results before advancing state.
Cross-application atomicity is not assumed; partial completion is reported.

## Backends

Execution is local Windows or SSH Windows. SQL discovery is local SQL, remote SQL,
or ODBC. These are independent transport choices, not three implementations of
business logic. Real SSH acceptance does not prove local Windows or ODBC acceptance.
GUI execution in an interactive Windows session is a separate capability from
headless execution over SSH.

## Autonomous delivery

The owner has authorized implementation toward the documented demo, testing, and
focused Git commits. Continue routine design and implementation without asking for
approval at each step. Preserve unrelated working changes. Use the demo environment
and explicitly disposable targets for live mutations; do not repurpose unrelated
source repositories or shared databases for destructive acceptance tests.

Ask for help when credentials/access are unavailable, a decision materially changes
the agreed goal, or Workbench interaction needs a human. GitHub publication and
recurring background scheduling are separate actions, not implied by local commits.
No automatic scheduler is configured by this document. Work only runs while the
agent task is active or an explicitly configured automation is executing.

Every milestone records implementation, automated checks, live checks, limitations,
and outstanding manual acceptance. Make no claim of visual acceptance from XML
comparison alone. Keep local connection details out of committed records.

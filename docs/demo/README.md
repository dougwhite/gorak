# Community demonstration

Status: proposed walkthrough; not yet ready for recording.

This is the acceptance target for Gorak's autonomous implementation work. The demo
shows an existing OpenROAD application becoming a reproducible Git project, shared
between developers with separate source databases, then developed and tested from
an editor. Workbench remains the frame designer. CLI operation from Linux through
SSH is part of the target, not an optional alternative implementation.

See [delivery milestones](milestones.md), [architecture decisions](decisions.md),
and [acceptance evidence](acceptance.md). The updated roadmap includes the
[direct-storage investigation](../research/encoded-source.md), mandatory ODBC source
access, a proposed database tracking installer, and gigabyte-scale performance. Proposed commands below are illustrative;
only commands explicitly marked current are available today.

## Demo environment and reset

Use a small representative application with a frame, a procedure, a class, a
source include, an external image dependency, globals, and a test suite. Include
nested frame fields, event scripts, and field defaults so the demonstration tests
more than procedure text. Keep real customer source and connection settings out of
the published example.

Developer A and Developer B have separate working directories and separate
OpenROAD source databases. Neither database may be an existing production or
shared development database. Store connection configuration in ignored `.env`
files. Provisioning and resetting these disposable targets must be explicit and
must verify target identity before deleting anything.

A rehearsal script should prepare the starting state and record checks, while a
presenter walkthrough explains visible actions. Do not make hidden cached exports
or manual database repairs prerequisites. Keep failed-run artifacts for diagnosis.

## Act 1: Put the existing application into Git

Story: "Keep using Workbench. Start getting readable source history and reviews."

1. Show the running application and its source in Workbench.
2. Create a Gorak project and configure ODBC source access and OpenROAD execution.
   In the target stack, install/check Gorak database tracking explicitly.
3. Export selected applications and their source dependencies.
4. Explain the established compact `.w4gl`, nested `.wml`, app metadata and
   inherited field defaults: these contain the supported readable source.
   XML transport, baselines and recovery evidence stay under ignored `.openroad`.
   Existing compact projects need no format migration or source-format flags.
   Only earlier experimental preview/companion checkouts need `gorak migrate-source`;
   review that conversion and preserve its binding and recovery state.
5. Show that credentials, local synchronization state, and logs are ignored.
6. Commit the exported project and inspect a readable component in Git.

Current: `gorak new NAME`, `gorak config ...`, `gorak app export APP`.
Target extension: multiple applications and explicit recursive dependency export.
External image references must be reported, not mistaken for source applications.

Exit criterion: a fresh clone contains all source needed for Act 3.

## Act 2: Continue working in Workbench

Story: "Existing development habits now produce reviewable Git changes."

1. Edit a component, add another, and delete a disposable component in Workbench.
2. Run `gorak status` (current) and inspect the pending pull plan.
3. Run `gorak sync` (current; database-side deletions supported, broader recovery pending).
4. Show accurate added, modified, and deleted files in `git status` and `git diff`.
5. Optionally ask an AI assistant to review the diff, then commit it.
6. Include a frame-design edit and demonstrate its preserved export.

Exit criteria: unrelated files remain unchanged; local edits cannot be silently
lost; one-component export cannot mark unrelated components as synchronized.

## Act 3: A second developer starts from Git

Story: "Each developer has an independent OpenROAD workspace."

1. Clone the project into Developer B's directory, with no `.openroad` cache.
2. Configure a separate, empty initialized source database.
3. Restore locked Git dependencies once that feature exists.
4. Preview and push source into the empty database.
5. Re-export and compare source, then run the application and tests.
6. Developer A makes a change, pulls it from Workbench, commits, and pushes Git.
7. Developer B pulls Git and pushes the source change into B's database.
8. Show a branch switch followed by an explicit synchronization plan.

Conflict scene: B edits a component in Workbench. A deletes its app and commits
that deletion. After B pulls Git, Gorak identifies delete-versus-edit and stops
without deleting B's source. Show the recovery/resolution choices.

Exit criteria: cloning is genuinely self-contained; frame source survives;
conflicts and target switches cannot reuse an inappropriate baseline; deleting an
unchanged object is supported only through an explicit reviewed plan.

## Act 4: Add tests and develop on disk

Story: "The database can be the compiler and runtime for editor-authored code."

1. Install a Git-hosted test framework dependency at a locked revision.
2. Create a test application that includes the framework and example applications.
3. Scaffold a runner and a test class, with discovery/registration defined.
4. Write a failing test; synchronize and run it from the CLI.
5. Show the assertion, filename/line location, machine-readable XML, and nonzero exit.
6. Implement the change on disk; repeat the same command and show a passing result.
7. Commit the test and implementation together.

Current: `gorak new app NAME --test` creates an empty registered test app;
`gorak sync --push && gorak test` is the working explicit sequence.
Proposed: framework-aware scaffolding, `gorak new test`, and `gorak test --sync`.
A synchronization failure must prevent the run. With proposed deferred compilation,
compilation errors during launch must clearly fail the command; execution cannot
report stale or misleading success. Explicit compilation remains available.

## Act 5: Build and use the editor

1. Build the full application image using the CLI.
2. Build included application images in dependency order.
3. Repeat unchanged and demonstrate that no rebuild is required.
4. Change an include and show correct dependent rebuilds.
5. Run a component with an editor task/keybinding and collect diagnostics.
6. Ask an AI assistant to implement a bounded feature using the same documented
   CLI, then inspect its diff and tests. Record actual intervention required.

A visible Windows frame launch is a separate acceptance check from headless SSH
execution. Do not imply an SSH service session automatically controls Workbench.

## Gold-star extension: Watch and editor tests

Operate with file-save synchronization and editor test actions. Tests discover
correctly, failures navigate to their source, and conflicts interrupt automatic
writes. Watch mode shares the explicit sync planner, survives restarts, avoids
feedback loops, and handles atomic editor saves. It must never treat a failed
import as a new successful baseline.

This extension is in the roadmap, but should not block recording the core demo
once Acts 1–5 have reproducible evidence. Full autonomous AI authoring of frame
layouts and a dedicated MCP server are later capabilities, not recording gates.

## Performance and storage scene

Show no-change status and push against a representative large repository, then one
changed component and a test run. Report cold/warm and variable latency honestly.
The target is sub-second no-change checks with bounded metadata traffic, not a
full download/hash of gigabytes. Demonstrate journal-driven detection, candidate-only
ODBC reads, and no source-export OpenROAD startup once those capabilities are built.
Do not present direct decoding/saving or database tracking as currently implemented.

## Recording gate

- [ ] Acts 1–5 rehearsed from a documented disposable starting state.
- [ ] No original cache or unrecorded database repair needed by Developer B.
- [ ] Conflict scene preserves both developers' work.
- [ ] Red-to-green test loop and image build verified.
- [ ] Frame round trip verified in Workbench by a human where required.
- [ ] Exact revision, commands, tool versions, and artifact locations recorded.
- [ ] Known limitations stated honestly; unresolved bugs remain in the ledger.
- [ ] Presenter accepts the walkthrough and recording scope.

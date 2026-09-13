# Delivery milestones and gap ledger

Status as of 2026-09-13. This document is the implementation backlog, not a claim
that the proposed command surface is already implemented. Work in dependency
order; make focused commits after proportional checks pass. Keep implementation,
live acceptance, and presenter acceptance separate.

| ID | Milestone | State | Acceptance gate |
| --- | --- | --- | --- |
| M0 | Preserve baseline and document demo | Complete | Existing work committed; walkthrough, decisions, gaps, evidence linked |
| M1 | Self-contained source and fresh-clone reconstruction | Not started | Clone without cache → empty DB → equivalent export, runnable app/tests |
| M2 | Safe shared sync planner and status | Not started | One-sided edits/additions/deletions work; divergent changes never overwrite silently |
| M3 | Onboarding and dependency-aware export | Not started | Multiple apps exported with source include closure and clear external-image requirements |
| M4 | Locked Git dependencies | Not started | Clean checkout restores identical dependency sources; explicit updates alter lock |
| M5 | Test scaffolding and combined test workflow | Partial | Scaffold → failing test → fix → pass, with diagnostics and repeatable CLI execution |
| M6 | Builds and execution | Partial | Full and incremental image builds; CLI component run; dependency invalidation verified |
| M7 | Editor tasks and community rehearsal | Not started | Documented keybindings, diagnostic navigation, full two-developer rehearsal |
| M8 | Watch mode and rich editor testing | Not started | Shared planner, restart safety, no loops or silent conflicts; editor discovery/navigation |

## M1: Source portability

- [ ] Define a versioned source format and format migration policy.
- [ ] Preserve XML structures not yet represented by readable files in tracked
  source companions; credentials and target-specific sync state stay untracked.
- [ ] Define which readable fields override preserved XML; reject inconsistent or
  unsupported edits instead of dropping content.
- [ ] Export and reconstruct frames, globals, 3GL declarations, app metadata,
  includes, field defaults, class declarations, scripts, and opaque source data.
- [ ] Preserve script CDATA and significant whitespace; stabilize repeated exports.
- [ ] Distinguish source equality from destination-specific IDs and timestamps.
- [ ] Restore a real representative application into an independent empty target.
- [ ] Verify frame rendering and interaction separately from XML equality.

## M2: Synchronization correctness

- [ ] Three-way content/inventory baselines bound to an explicit database identity.
- [ ] Shared read-only plan for status, pull, push, and later watch execution.
- [ ] Track application membership independently of existing component-state entries.
- [ ] Protect disk changes during pulls, including multi-component app exports.
- [ ] Handle component and application deletion on either side.
- [ ] Detect edit/edit, delete/edit, rename/case collisions, and missing baselines.
- [ ] Expose explicit resolution choices and retain recoverable artifacts.
- [ ] Avoid advancing unrelated baselines and avoid marking failed writes as synced.
- [ ] Protect against concurrent commands, local edits during execution, and DB drift.
- [ ] Test branch switches, cloned directories, changed targets, and interrupted runs.

## M3–M4: Configuration and dependencies

- [ ] Setup/check command that diagnoses OpenROAD, SQL, SSH helpers, and runtime needs.
- [ ] Keep execution backend and SQL transport independent; no duplicated feature logic.
- [ ] Multiple-app export and include graph traversal with cycle/missing-node handling.
- [ ] Git source declarations separate from each app's OpenROAD includes.
- [ ] Deterministic ignored install directory, tracked lock file, explicit install/update.
- [ ] SSH Git URLs, exact commit resolution, clean clone reproducibility, useful failures.
- [ ] Collision policy for app names exported by multiple dependencies.
- [ ] Detect local dependency edits; never discard them on update.
- [ ] No implicit execution of dependency installation hooks.

## M5–M6: Tests and builds

- [x] Existing CLI run/test path and XML result parsing, including SSH execution.
- [x] Empty test app registration and manually authored failing-test loop.
- [ ] Framework-aware scaffolding and a test class generator.
- [ ] Explicit sync-before-test orchestration; no tests after failed compilation.
- [ ] Stable machine-readable diagnostics with disk source locations.
- [ ] Missing/malformed reports, timeouts, skips, failures and process cleanup tested.
- [ ] Full image build with configurable output and retained compiler diagnostics.
- [ ] Included-image dependency graph and deterministic artifact manifest.
- [ ] Incremental keys include source, included interfaces/artifacts, compiler identity,
  build flags, external images, and relevant configuration.
- [ ] Headless component execution distinguished from visible GUI launch.

## M7–M8: Delivery and editor experience

- [ ] Install/upgrade and Windows quoting/path tests; package resources verified.
- [ ] VS Code task examples for tests, builds, and component execution.
- [ ] Test discovery and source navigation integration.
- [ ] Reproducible rehearsal fixtures and explicit reset for disposable targets.
- [ ] Automated feature authoring scene with human review and intervention recorded.
- [ ] Watch debouncing, atomic saves, deletion events, retries, restarts, and conflicts.

## Cross-cutting maintenance

Refactor growing orchestration into source representation, planning, execution,
backend transport, and reporting as those boundaries become clear. Maintain module
and CLI tests, use generic tracked fixtures, and keep command docs factual. Record
new bugs under the milestone they block. Do not let a successful demo erase known
bugs or substitute for broad source compatibility claims.

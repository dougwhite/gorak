# Acceptance evidence

## Baseline: 2026-09-13

Implementation commit: `2c4b4d9` (application scaffolding and verified source push).

Automated: 340 pytest tests passed; Ruff and strict mypy passed. These results
precede M1 work and must not be interpreted as full source portability coverage.

Live SSH checks in the owner's demo environment:

- New empty app imported from disk.
- New procedure and class imported; exported source compared.
- New app with source include and starting procedure created and run headlessly.
- Existing app includes/starting component updated with preserved XML.
- Compilation after app metadata update moved into a fresh OpenROAD process so
  newly configured includes are visible.
- Test runner and intentional failing assertion imported and executed by CLI.
- Test result: two XML testcase entries (setup plus one test), one assertion
  failure, zero errors/skips, process exit 1.
- An earlier smoke class had an invalid `self` reference; corrected to `CurObject`
  and pushed successfully. Failed import artifacts retained locally.

Not verified: cache-free full clone restoration, frame GUI behavior after import,
local Windows execution on a separate installation, ODBC variant of the full demo,
images, deletion/conflict workflow, Git dependency installation, editor integration,
watch mode. The demonstration is not recording-ready.

## Milestone evidence template

For each milestone record:

- Revision(s) and source-format/helper versions.
- Acceptance scenario and disposable target identity (local-only identifiers in
  private run artifacts, generic labels in this document).
- Exact commands and actual exit/results; distinguish expected test failure.
- Automated checks and live transport combinations exercised.
- Artifact paths or stable references that do not expose private connection data.
- Untested scenarios, manual Workbench steps, new bugs, and recovery interventions.
- Implementation status, live acceptance status, and presenter acceptance status.

## M1: Cache-free reconstruction, 2026-09-13

CLI acceptance passed; owner-confirmed visual acceptance passed for the two demo frames.

- Exported four demo applications, 30 components, and two frame markup files into
  a separate source checkout. Coverage includes an empty app, source/image includes,
  classes, procedures, globals, a 3GL declaration, and the unit-test framework.
- Committed readable files and format-1 XML companions; cloned with Git into a
  directory containing no `.openroad` cache. Local environment supplied separately.
- Created an independent standard Ingres database using `createdb TARGET -no_x100`.
  The plain command attempted X100 creation and failed on this installation.
  See [Actian createdb reference](https://docs.actian.com/ingres/11.0/CommandRef/createdb_Command--Create_a_Database.htm).
- `gorak sync --push`: four application creations succeeded; whole-app compilation
  used fresh processes. Each preserved component passed complete XML comparison
  after import, not only the readable-property subset.
- Re-exported all four apps; `git diff --exit-code` succeeded and the saved diff
  was zero bytes. No hidden source cache was supplied to the initial import.
- `gorak test`: expected exit 1, one deliberate assertion failure, zero errors or
  skips. Two testcase entries include setup. This proves test execution rather
  than a green application suite.
- Automated checks: 347 pytest tests pass; Ruff and strict mypy checked before commit.
- Private acceptance checkout/artifacts: `/tmp/gorak-m1/clone-clean`; retained logs
  also document failed attempts. These temporary paths are evidence pointers, not
  dependencies of the portable source format.

Issues fixed during acceptance: compilation within backupapp could see incomplete
class/global state; creation now compiles whole apps in a fresh process. Broad log
matching incorrectly treated `Error` and `AssertionFailedError` component names as
errors; diagnostics distinguish these names from error messages. Component export
filename casing is respected when writing companions.

The owner subsequently opened both reconstructed demo frames in Workbench and
reported that they worked perfectly, supplying a screenshot showing the simple
frame and `fm_complex_frame`. This completes the representative visual check;
it is owner-performed acceptance, not an automated UI test. Exhaustive event and
interaction behavior was not separately enumerated.

Connection-profile setup initially used a truncated database name after a qualified
connection string was pasted into the database field. Using the full unqualified
database name resolved it. Demo instructions should present node and database
values separately and use short disposable names.

Broad binary/opaque structure coverage beyond the sample, format migrations beyond
rejecting unknown versions, deletion handling, and target-bound synchronization
safety remain open.

## M2 first slice: planning and CLI safety gates, 2026-09-13

Implementation is partial; the new execution engine and deletion handling remain open.
Automated: 385 pytest tests pass; Ruff and strict mypy pass. Tests cover the complete
27-state comparison matrix, deletion versus child edits, malformed local projections,
read-only status, target mismatch, explicit binding, and conservative execution gates.

Live checks against the retained isolated acceptance database:

- Unchanged accepted clone produced an empty change list.
- Explicit binding verified the cached baseline and recorded the configured target.
- A temporary disk script edit caused pull to stop; the edited bytes remained intact.
- Independent edits of the same procedure in disk and database caused push to stop
  with both sides reported modified. The original database and local script were
  restored in a finally block. Private evidence: `/tmp/gorak-m1/conflict-check`.

Not yet verified/implemented: safe deletion execution, converged-state advancement,
shared locks and atomic snapshot validation, target remapping detection, efficient
scans, and the complete two-developer rehearsal. CLI checks do not make the older
internal Python execution functions safe for direct callers.

## M2 staged pull slice, 2026-09-13

The CLI now stages affected applications, revalidates disk and database snapshots,
and retains before-images and a journal when installing source/cache changes.
Focused tests cover rollback on write failure, local edits during staging, database
drift during staging, last-moment snapshot mismatch, and app deletion preserving
unrelated notes. Full validation: 389 tests, Ruff, and strict mypy pass.

Live acceptance used a disposable probe application in the retained isolated target:

- Independently changed procedure source and application description in the database,
  and added a database component; pull installed all three changes.
- Deleted that added component in the database; pull removed its readable source
  and portable companion.
- Deleted the probe application in the database; pull removed tracked app source
  and cache while preserving its human notes file.
- Final status reported a verified target and no changes; no pending recovery marker
  remained. The four original acceptance applications were preserved.

Database-side deletion pushes, shared mutation locking, automatic crash recovery,
and broader compatibility acceptance remain open. The previous first-slice limits
above describe the earlier checkpoint rather than current pull capability.


## M2 shared checkout lock, 2026-09-13

CLI source mutations now acquire a common exclusive lock before planning or backend
work. Automated checks cover contention, release after failure, unfinished pull
markers, and each guarded command entry point. The existing external-service test
guard remained enabled: no live database or SSH calls were needed for this slice.
Full validation: 400 tests, Ruff, and strict mypy pass.

The lock coordinates a single checkout. External editors, Workbench, other
checkouts, and direct Python calls remain outside its scope. Push snapshot
revalidation and deletion execution remain open.

## M2 push snapshot and recovery slice, 2026-09-13

Automated checks cover files added during preflight, a database application appearing
before creation, and a disk edit during import. The latter retains returned XML,
leaves creation caches unadvanced, and blocks retry with a recovery marker. Existing
creation, metadata update, portable restoration, and script-import tests also pass.
Validation: 404 tests, Ruff, and strict mypy. No live acceptance was run for this
slice; database-write atomicity, complete baseline staging for script imports, and
automatic recovery remain open.


## M2 staged script baselines and verified push recovery, 2026-09-13

Push defers script-import cache updates until all database operations and source
checks succeed, then installs caches through the before-image/rollback helper.
Standalone component imports retain their existing immediate verified-cache behavior.

`gorak recover push` can finish an interrupted operation when disk and database agree.
Tests cover successful baseline recovery, mismatched targets, divergent source,
concurrent disk/database changes, failed installation, and deferred script caches.
Validation: 412 tests, Ruff, and strict mypy pass. No live OpenROAD acceptance was
run for this slice. Partial database writes still need deliberate reconciliation;
recovery does not overwrite either source side or implement database rollback.


## M2b transactional journal prototype, 2026-09-13

Live ODBC tests on disposable source/journal/acknowledgment tables verified rollback,
reverse commit order, independent consumers, update and deletion capture. MVCC let a
reader observe a higher committed event while a lower event was still uncommitted;
explicit per-event acknowledgments preserved discovery of the late lower event.
Ordinary locking timed out rather than exposing the uncommitted row. An initial
writer-side journal scan caused contention and was removed from the probe.

This is transaction-mechanics evidence only: no production source rules, installer,
retention implementation, source coverage, or large-save performance acceptance.
Details and limitations: [journal research](../research/change-journal.md).


## M2b actual source-table rule probe, 2026-09-13

Twenty-four temporary rules on eight source-related tables captured the synthetic
application's script import, explicit compile, metadata/include replacement,
component deletion, and application deletion. Normal login permission was
insufficient; owner-identity bootstrap succeeded. Whole-app imports replaced entity
identities, confirming the need for richer tombstone context. Source-table rules,
procedure and sequence were removed afterward; the event table was retained.

No production installer, complete Workbench/frame/image coverage, failure-injection,
or large-save overhead claim. See [source-rule coverage](../research/source-rule-coverage.md).

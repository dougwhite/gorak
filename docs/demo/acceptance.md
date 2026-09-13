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

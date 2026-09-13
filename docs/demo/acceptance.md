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

# Community demo rehearsal

Status: **frame visual acceptance passed; feature/reset rehearsal verified**.
The recording itself has not been timed or performed.

The release gate is readable `.w4gl` and `.wml` re-import for the represented
component types, a visually usable app, synchronized tests, and a reproducible
feature pull request. No native storage rewrite or revision installer is required.

## Environment

- Python 3.12+, installed editable Gorak, Git and authenticated GitHub CLI.
- OpenROAD 12 Windows execution host, SSH/SCP and packaged helpers version 8.
- An independent disposable source database with the Actian UnitTestFramework
  source application installed as `unittestframework` and its required runtime
  libraries configured. The demo repository does not redistribute that framework.
- Local-only `.env` containing source connection and any framework runtime
  environment settings. Source database identity and credentials are not committed.
- VS Code with the private demo checkout and Codex available. Workbench for the
  GUI check. The CLI test run does not establish that a GUI window appeared.

## Application

`launch_score` has four components:

- `launch_panel`: numeric capsule input, Calculate score button and numeric output.
- `p4_score`: deterministic integer calculation, initially 10 points per capsule.
- `test_launch_score`: one test method with several assertions (the framework also
  counts its setup method, so the baseline report contains two tests).
- `runtests`: calls the installed framework with the test class.

Manual visual acceptance must establish input 1 → score 10 and input 5 → score 50,
then close the frame and its editor before any further source imports.

## Recording sequence

Start from the verified demo baseline with a clean working tree and no pending
recovery state. The baseline tag is `demo-baseline-10`; measured command timings are below.

```sh
gorak sync
```

Manual edit: change `RETURN capsules * 10;` to `RETURN capsules * 12;`, and update
the one-capsule and five-capsule assertions to 12 and 60. Change the frame subtitle
from “10 points per capsule” to “12 points per capsule” in `launch_panel.wml`. Then:

```sh
gorak sync --push && gorak test
git diff
git add launch_score/p4_score.w4gl launch_score/test_launch_score.w4gl launch_score/launch_panel.wml
git commit -m "Set launch score to twelve points per capsule"
```

The manual change must be committed before Codex's clean-tree feature loop.
The optional `gorak status` performs an additional database comparison; omit it
from the shortest recording path once rehearsed, not from conflict diagnosis.

Give Codex this feature request:

> Add a fleet bonus to Launch Score: award 20 extra points when the capsule count
> is at least 5, while retaining 12 points per capsule. Add deterministic assertions
> for 0, 1, 4, 5 and 6 capsules. Update the Calculate score button's label to
> “Calculate launch score” in the frame markup, widening it to fit. Follow AGENTS.md: pull latest,
> implement on a feature branch, synchronize with Gorak and run the OpenROAD tests.
> Inspect the diff, commit the feature, push the branch and create a pull request
> against main in this private repository. Do not merge it. Report the test results
> and the PR link.

Expected results: 0 → 0, 1 → 12, 4 → 48, 5 → 80, 6 → 92. The diff should change
the procedure, existing test method, and button label in `.wml`. It should not
change private configuration, cached state or opaque source. The button width
changes from 1323 to 2000 to accommodate the label.
The video ends on the GitHub pull request, not on an automatically merged change.

A one-minute edited recording may need clearly visible cuts while the agent works.
Do not describe edited footage as a measured one-minute real-time implementation.
Use the fresh-process timings below to decide whether an uninterrupted take fits.

## Reset and cleanup

Use a baseline tag and a new feature branch/worktree for each take. Once all
intended work is saved, restore only the documented demo source paths from that
tag, then run `gorak sync --push && gorak test`. Never reset `.openroad`, target
binding, recovery, locks or managed generation state. A Git restore does not
restore database source; the verified push is mandatory.

For a new disposable database, use a fresh clone with its own local `.env`,
install the test-framework dependency, and run `gorak sync --push`. Keep old failed
operation artifacts for diagnosis. Database deletion is a separate DBA cleanup
step after all Workbench and writer processes are closed; Gorak has no ordinary
source-deletion push workflow.

If a nonessential GUI action fails while recording, stop and fix/rehearse it.
Do not substitute passing CLI assertions for a claim that the GUI worked. If GitHub
is unavailable, retain the verified local commit and retry publication before
recording the PR view. No successful-demo claim is made from an incomplete take.

## Evidence recorded 2026-09-14

- Actual CLI interfaces inspected: `sync`, `status`, `new`, `run`, `test`,
  configuration and remote helper commands. Tests do not imply synchronization.
- Local XML preservation: 157 corpus components exactly reconstructed; one local
  declaration without a baseline excluded. Twelve frame position edits passed
  installed-schema validation and readable round-trip checks.
- Disposable app creation imported four components; frame compilation initially
  failed because unqualified references targeted fields inside a named subform.
  Recovery refused divergent source as designed. Separate reconciliation export
  retained original failure evidence.
- The first frame layout push exposed compile-before-load behavior. Helper 8
  now imports and compiles in separate processes; corrected frame compilation
  succeeded. Test suite passed: 2 tests, 0 failures, 0 errors, 0 skipped.
- Geometry probe imported 17 coordinate values through OpenROAD 12. Examples:
  1 → 0, 10 → 10, 100 → 104, 250 → 250, 300 → 302, 321 → 323,
  729 → 729, 730 → 729, 1000 → 1000, 1100 → 1104, 1417 → 1417,
  23999 → 23999, 24000 → 23999. Coordinate canonicalization is restricted to
  logical-pixel-equivalent form geometry; full conflict checks remain exact.
- Initial generated controls were offscreen. Their inherited gravity was 17
  (center-left), positioning them within an oversized form. The owner built a
  native reference frame. New explicitly positioned controls now omit inherited
  palette gravity, and the unused offscreen prototype was removed through push.
- **Owner visual acceptance passed:** after a combined three-component push,
  Workbench showed the 12-point subtitle, wider Calculate launch score button and
  newly added “WML import works” text. The owner confirmed 1 → 12 and 5 → 60.
  The synchronized OpenROAD suite passed 2 tests with no failures or errors.
- An independent synthetic application was created and compiled, then all eight
  observed component types received description edits through one successful
  `gorak sync --push`: 8 verified component updates. An earlier invalid synthetic
  class fixture failed; its source and error logs were retained separately.
  This verifies declaration/source re-import, not execution of a 3GL library.
- Automated validation: 975 pytest tests passed, Ruff and mypy passed. The wheel
  built successfully and contains the agent instructions and XML protocol tables.
- The fleet-bonus draft PR was published without merging. Switching back to `main`
  and pushing restored the 10-point baseline; OpenROAD tests passed again.

## Measured command timings

Fresh CLI processes on the rehearsed small app and execution host:

| Command | Seconds | Result |
| --- | ---: | --- |
| `gorak sync` | 1.187 | No pending database changes |
| `gorak sync --push` (three-component reset) | 5.763 | Verified |
| `gorak test` | 1.381 | 2 tests, no failures/errors |
| `gorak sync --push` (unchanged) | 1.048 | No component updates |

These measure the CLI, not agent reasoning, GitHub latency or an end-to-end video.
Network and application size affect results. No uninterrupted one-minute claim is
made. The manual 12-point edit and fleet-bonus feature were subsequently pushed and
tested successfully; expected boundary assertions passed.

The private demo keeps `main` at `demo-baseline-10`, the manual rehearsal on
`codex/rehearsal-manual`, and the feature on `codex/fleet-bonus`. The draft rehearsal
PR targets the manual branch so `main` remains reusable. For recording against
`main`, commit the manual edit there first, as described in the feature prompt.


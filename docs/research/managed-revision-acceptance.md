# Managed revision acceptance

The four delivery steps are implemented together under the explicit
[managed revision contract](../revision-mode.md):

1. Local and SSH OpenROAD launchers use the shared execution-host worker.
2. Quiet diagnostics compare against compact semantic snapshots guarded by complete
   before/after revision vectors and installation checks.
3. Snapshot continuity uses target/scope/generation binding, bounded expiry and
   offline DBA generation rotation. It does not depend on per-event receipts.
4. Configured normal status and push preflight use this path, with full XML refresh
   on any dirty vector, expiry or unusable cache.

This replaces the initial proposed event-consumer compaction step with a simpler
whole-snapshot protocol. It does not implement selective dirty refresh or online
counter pruning. Historical journal diagnostics retain their own consumer state.

## Automated checks

Final verification: 755 pytest tests passed; Ruff and strict mypy passed.

Regressions cover quiet reuse without exports, disk edits, changed/reused writer
lanes, unavailable/partial vectors, damaged and expired checkpoints, clock rollback,
scope changes, old checkout restoration, generation replacement, capture damage,
writer commits during export, and failed atomic local publication. Reference
verification compares the full semantic hash inventory, not merely change labels:
two different database versions can both be classified as a pull.

An oracle mismatch or observed capture damage quarantines the generation. Repairing
SQL definitions without a generation transition remains blocked. Offline reset tests
exercise valid reset, absent/duplicate/wrong parent and wrong schema, checking that
failed guarded transactions preserve generation and counter rows.

Worker tests exercise deterministic packaging, argument validation, selected
installation lookup, startup preservation, process exit propagation, cleanup and
failure output. Existing local runner and source/CLI regressions remain in the suite.
Route regressions reject mismatched or ambiguous source generations before export,
invalidate checkpoints when ODBC endpoints change, and prevent managed runtime
overrides from selecting another Ingres installation. Automated tests do not connect
to developer services.

## Live Windows and ODBC acceptance

A disposable helper deployment and revision extension were installed against an
existing isolated source database. A new procedure application was imported and
compiled using the packaged helper, exported to a temporary checkout and bound.
A pre-existing complex frame example was exported into the same checkout; its
source was not edited.

The following passed:

- Full bootstrap followed by quiet reuse, then explicit full-XML oracle comparison.
- Separate CLI-process status runs through the project configuration.
- A rolled-back captured event leaving the revision sample unchanged.
- A disk edit reported as push, a real `sync --push`, a fresh clean comparison and a
  subsequent no-change push.
- Managed application execution and the existing unit suite: two tests, one expected
  intentional failure, zero errors, process exit 1. The suite's failure was correctly
  returned; it is not reported as a passing test suite.
- A native harmless timeout fixture launched directly through the managed execution backend:
  timeout status 124, the child process gone, and generated startup file removed.
- Missing capture rule detected, followed by persistent quarantine after restoring
  the rule body.
- Offline generation rotation rejecting old configuration and invalidating a saved
  old checkpoint after clients adopt the new generation.
- Database deletion of the disposable app detected, with a conflicting push blocked.

The scratch app, revision extension, timeout fixture and temporary helper deployment
were removed. Original parent tracking identity and structural checks remained
healthy. The ordinary working checkout and Workbench launchers were not enrolled or
changed. The production worker was exercised on Windows through SSH; complete native
Windows CLI orchestration remains covered by isolated automated tests rather than a
separately installed full Windows Gorak environment.

## Timings

These are measured samples from the isolated run, not performance guarantees. The
final checkout contained about 156 KB of baseline XML including complex frames.

| Operation | Measured time |
|---|---:|
| Quiet status, fresh CLI process, three samples | 0.449, 0.481, 0.444 seconds |
| No-change push, fresh CLI process | 0.451 seconds |
| Changed procedure push, fresh CLI process | 2.811 seconds |
| Status after that push, requiring refresh | 1.690 seconds |
| In-process initial full bootstrap | 2.493 seconds |
| In-process quiet comparison | 0.148 seconds |
| In-process explicit full-reference verification | 2.494 seconds |
| Managed application run including transport | 1.999 seconds |
| Managed unit suite including transport | 2.094 seconds |

Earlier one-procedure samples were about 0.35 seconds for quiet CLI status/push.
The final managed paths include helper/version and matching-generation checks through both ODBC and the source-host SQL route.
Quiet comparisons read no database XML and no event/receipt history. Local baseline
and source parsing still scales with local source bytes. No gigabyte-scale latency,
new physical-restore rehearsal, additional manual Workbench save-path coverage, or
multi-server certification is claimed by these measurements.

## Managed pull integration follow-up

A manual procedure-remark edit was detected through revision invalidation and agreed
with the full XML oracle. Ordinary pull then exposed nested lock acquisition:
CLI sync held the mutation lock, while pull planning attempted to acquire it again.
The failure occurred before source installation; the operation released its locks.

Pull now explicitly reuses CLI lock ownership, and direct service calls acquire the
mutation lock before creating the pull marker. Regressions exercise real managed
planning and staged installation through both entry points, plus rejection of a
competing operation without removing its lock. The full suite passed 758 tests;
Ruff and mypy passed. Live retry pulled the single procedure change and subsequent
status reported no differences using revision reuse.

A first status after even a remark edit still performs full XML refresh and can take
several seconds. Repeated status on that same snapshot is fast. Changed-source
latency remains a separate acceptance gate: object-level invalidation and direct
ODBC semantic comparison must avoid XML startup while preserving full-reference
agreement and explicit fallback for unsupported cases.

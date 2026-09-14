# Import an existing component

Use `gorak sync --push` for the ordinary project workflow. The scoped command
`gorak component import APP COMPONENT` imports one existing component using its
cached XML baseline:

```sh
gorak sync
# Edit the component's .w4gl and, for a frame, .wml.
gorak component import example_app example_procedure --dry-run
gorak component import example_app example_procedure
gorak test
```

Run inside the project. Remote users must install helper version 8 with
`gorak remote install`; local users need an initialized OpenROAD environment.
The command accepts the same connection flags as component export.

## Readable edits and verification

The importer overlays scripts, represented component metadata and frame markup
onto preserved XML. See [component editing](component-editing.md) for the observed
types, field defaults, layout behavior and limits. Unedited opaque XML is retained.
Creation belongs to [push](push.md), not this existing-component command.

The baseline comes from the newest component or application export in the local
cache. Before writing, Gorak exports the database component and requires exact
agreement with that baseline. It imports the prepared XML, compiles the component
in a fresh process, and verifies a fresh full export. Only the documented frame
coordinate conversion permits non-identical XML. Verified canonical WML is staged
with the new cache, and should be reviewed in Git.

Dry runs compare the database and prepare XML without importing or advancing the
baseline. Tests run database source; require a successful push/import before tests.

## Conflicts and recovery

Conflict checks are optimistic, not an atomic database compare-and-write lock.
Keep Workbench editors closed while importing, and do not run overlapping project
operations. Stop on a conflict and retain both versions. Do not delete locks,
baselines, recovery markers or quarantine to bypass a refusal.

Artifacts in `.openroad/imports/ID/` retain source, baseline, `before.xml`,
`submitted.xml`, logs and, when available, `after.xml`. A `verified` marker records
successful XML verification. Compilation or verification failure may leave changed
database source: failure does not imply rollback. Inspect the retained evidence
before reconciling. Gorak does not automatically restore an old export over a
potentially newer Workbench change. Project push additionally maintains its pending
recovery state; follow its reported `gorak recover push` guidance.

Keep connection settings, XML caches and diagnostic logs out of Git. Portable
source companions under each app's `.gorak-source/` are tracked separately.

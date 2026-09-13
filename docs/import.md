# Import existing component scripts

`gorak component import APP COMPONENT` imports script edits to an existing
`proc4glsource` or `classsource` component. Run it inside a Gorak project, using
the application and component names as exported on disk.

```sh
gorak component export example_app example_procedure
# Edit example_app/example_procedure.w4gl below the === separator.
gorak component import example_app example_procedure --dry-run
gorak component import example_app example_procedure
```

The command accepts the same backend/connection flags as component export.
Remote users must run `gorak remote install` to install the current helper set (version 3) before
using import. Local imports require an initialized OpenROAD command environment.

## What is supported

The importer preserves a cached XML component, replaces its script, imports with
component selection, replacement and forced compilation, and re-exports it.
It compares all component XML content before reporting success. Unsupported
metadata remains in the XML, including structures not exposed by `.w4gl`.

The baseline can come from a component or application export. The newest cached
export by filesystem modification time is used. Keep the cache with the project;
do not copy unrelated XML into it or switch targets without reviewing the target
and exporting a matching baseline. Cache files from a fresh clone are not enough
to reconstruct an application: this is an existing-component editing workflow.

Metadata edits, new components, frames, `.wml` edits and application imports are
not supported. A frame's scripts must still be edited in Workbench for now.
Remote write commands reject shell metacharacters in connection settings and
support Windows helper root paths with spaces.

## Conflicts and recovery

Before importing, Gorak exports the current database component and compares it
with the baseline. Any XML content change blocks the import. Keep your local
edit separately when reconciling; existing `export` and `sync` commands can still
overwrite local edits and are not a conflict resolution tool.

This check is **optimistic**, not an atomic database lock. Do not edit the same
component in Workbench during import. A local lock prevents overlapping imports
in the same project, but does not coordinate other projects, export, or sync.
Do not run those operations concurrently. After a crashed import, inspect the
operation before manually removing `.openroad/imports/import.lock`.

Each operation retains `.openroad/imports/ID/` containing the edited source,
cached baseline, fresh `before.xml`, and `submitted.xml`. An actual import also
records `import.log` and, when available, `after.xml`. A `verified` marker means
XML verification completed. Dry runs perform the read-only database comparison
and prepare XML but do not import or update the baseline.

Compilation failure can still leave a changed component in OpenROAD. A failed
command or verification does not imply rollback. Inspect the log and database
before retrying; `before.xml` is the recovery copy. Gorak does not automatically
restore it because doing so could overwrite a subsequent Workbench edit.
Successful imports atomically replace only this component's cached XML and leave
local source and all component sync markers unchanged.

The remote helper retains uploaded `import-ID.xml` and its `.log` in the helper
root for diagnosis. Remove old operation artifacts manually when no longer needed.

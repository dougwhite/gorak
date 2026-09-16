# Push source changes

Run inside a Gorak project:

```sh
gorak sync --push --dry-run
gorak sync --push
```

Push validates readable source, imports all planned source, verifies fresh exports,
and installs source baselines. Compilation runs afterward, in fresh processes.
A compiler error does not undo a source import, fail the source sync exit status,
or put the project into recovery. The summary names each failed component and
prints the explicit compile command and saved log path.

```sh
gorak compile example_app widget
gorak compile example_app
```

These commands compile **database source**, not unpushed disk files. They print the
full diagnostics and retained log location, and exit nonzero on compilation failure.
The component argument is optional; omitting it force-compiles the application.
Failed/deferred push compilation remains in a separate queue and is retried by a
later successful push, including an otherwise unchanged push.

New applications are built from `app.json` and readable components. Source includes
are ordered before dependent applications. External image includes must be available
to OpenROAD. Existing source retains baseline XML details that the readable format
does not represent. Application metadata updates bundle components and preserve the
full application XML. Imports retain optimistic drift checks and source verification.
The compact format supports the eight observed component types, including nested
frame markup and field events; unknown source shapes are refused.

## Retry an interrupted push

Usually, just run `gorak sync --push` again. Gorak retains the before-images and
submitted XML and compares them with fresh database exports. It recognizes source
already accepted by OpenROAD, even if the import response was lost, refreshes those
verified baselines, and replans the remaining edits. Newer disk edits can be pushed
over the recognized previous attempt. A normal retry never assumes that an unrelated
Workbench edit was part of its own operation. Such changes remain ordinary conflicts.

An interruption is recorded, but is not itself a recovery requirement. A source
verification failure, unreadable operation evidence, or incomplete baseline installation
requires explicit reconciliation. `gorak status` reports the pending operation and
source differences when comparison is available. Diagnostic comparison failures are
reported as unavailable, not as proof of no changes.

A dry run does not reconcile a pending attempt or advance baselines. With a pending
attempt, use status to inspect or a normal push to retry. All operations remain
optimistic: keep Workbench editors closed during imports.

## Choose an authoritative side

```sh
gorak recover push                    # Finish only if disk and database agree
gorak recover push --take disk        # Disk wins for source present on disk
gorak recover push --take database    # Database wins for the tracked project
gorak sync --push --force             # Same disk-authority policy
```

The side choice applies to the **whole tracked project**, not just the component
that first failed. Before replacing anything, Gorak retains readable disk source,
previous markers, displaced baselines, and a fresh database export under
`.openroad/pushes/`. Database authority replaces tracked readable source (including
removing local-only components) but preserves unrelated files such as notes.
Disk authority imports local source; it never deletes database-only components.

Force can rebuild damaged source baselines and supersede a failed operation. It
still requires a verified binding to the original configured target. It cannot
bypass a live writer, invalid readable source, revision quarantine/generation checks,
or post-import source verification. It clears recovery only after the selected
source and tracking are installed successfully; compilation failure does not prevent
that completion. `--force` requires `--push` and is not combined with `--bind` or
`--dry-run`. A failed forced operation retains evidence and recovery status.

New lock records identify the owning host, process, and process start time. A
proven-dead local owner can be reclaimed; an active, remote, or unidentifiable owner
still requires inspection. Do not manually delete markers or baselines to retry.

Ordinary push does not implement database-side deletions. Removing local source or
finding a previously exported object absent from the database remains a conflict
unless an explicit authority choice resolves it.

## Backends and artifacts

Local Windows and SSH OpenROAD backends are supported. SQL discovery may use local,
remote, or ODBC access; source import and compilation use the OpenROAD backend.
SSH users must run `gorak remote install` for **helper version 9**, which separates
import from compilation. Older helpers are refused before upload. Helpers were
updated and covered by mocked backend tests; live Windows acceptance is separate.

Push XML, snapshots and compilation logs remain under `.openroad/pushes/`; existing
component imports also retain `.openroad/imports/` artifacts. Explicit compile logs
are under `.openroad/compiles/`. Keep these private diagnostics out of Git.

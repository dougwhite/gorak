# Push source changes

Run inside a Gorak project:

```sh
gorak sync --push --dry-run
gorak sync --push
```

Push discovers application folders containing `app.json`. New applications are
created from that metadata and their `.w4gl` files, without needing cached XML.
New source includes are ordered before applications that depend on them. External
image includes are passed through; the image must be available to OpenROAD.

Supported creation includes empty applications, 4GL procedures, and user classes.
Class attributes and methods support type declarations, arrays, nullability,
private methods, and return types. Unknown metadata is rejected. New frames and
other component types are not supported yet.

Existing procedures and classes use the script-only importer and its cached XML
baseline. Database changes since that baseline cause a conflict. Application metadata updates preserve the latest full application XML, check for
database drift, and bundle new components before importing. Compilation runs in a
fresh OpenROAD process so newly added includes are available. Component metadata
changes and frame changes are rejected.
Unchanged frames can coexist with pushed procedures and classes.

All planned source is validated before imports begin. Creations use OpenROAD's
abort-on-conflict option, and imports are re-exported to verify the result.
Empty applications skip forced compilation. A second unchanged push does nothing.

Push does not delete applications or components. Removing a disk file does not
remove its database object. A previously exported object missing from the database
is a conflict; reconcile that deletion explicitly before pushing. This is an
explicit push command, not a bidirectional newest-wins synchronizer.

XML and logs are retained in `.openroad/pushes/`; existing script imports also
retain `.openroad/imports/` artifacts. A push is not a transaction across all apps:
if a later operation fails, earlier operations may already have succeeded.
Inspect the retained XML and logs before retrying. Avoid simultaneous Workbench
edits while pushing; conflict detection is optimistic.

Both local Windows and SSH OpenROAD backends are supported. SQL discovery may use
local, remote, or ODBC access; XML imports still require the OpenROAD backend.
SSH users must run `gorak remote install` to install helper version 5, which adds
creation and application-update helpers. A missing creation helper fails without falling back to
replacement imports.

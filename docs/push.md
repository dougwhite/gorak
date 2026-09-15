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

The established compact source format supports reconstruction of all eight
observed component types, including nested frame markup and field events. No saved
XML, source-format flags or migration is required for existing compact projects.
Unknown source shapes are refused. See [source formats](files.md).

Existing components are rebuilt from the same readable representation.
Database changes since the baseline cause a conflict. Application metadata updates
preserve the latest full application XML, check for database drift, and bundle new
components before importing. Compilation runs in a fresh OpenROAD process so newly
added includes and imported source are available.

All planned source is validated before imports begin. Creations use OpenROAD's
abort-on-conflict option, and imports are re-exported to verify the result.
Whole applications compile in a fresh process after import; empty applications
skip compilation. A second unchanged push does nothing.

Push does not delete applications or components. Removing a disk file does not
remove its database object. A previously exported object missing from the database
is a conflict; reconcile that deletion explicitly before pushing. This is an
explicit push command, not a bidirectional newest-wins synchronizer.

XML and logs are retained in `.openroad/pushes/`; existing component imports also
retain `.openroad/imports/` artifacts. A push is not a transaction across all apps:
if a later operation fails, earlier operations may already have succeeded.
Inspect the retained XML and logs before retrying. Avoid simultaneous Workbench
edits while pushing; conflict detection is optimistic.

Both local Windows and SSH OpenROAD backends are supported. SQL discovery may use
local, remote, or ODBC access; XML imports still require the OpenROAD backend.
SSH users must run `gorak remote install` to install helper version 8, which imports source before fresh-process compilation. A missing creation helper fails without falling back to
replacement imports.

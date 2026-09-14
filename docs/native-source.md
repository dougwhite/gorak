# Native source snapshots (experimental)

`gorak source` transports current OpenROAD source through ODBC without invoking
XML export or import. It captures a complete application/include closure into
tracked native graph files and restores that snapshot into an **empty source
database** with newly allocated entity IDs.

This is a snapshot/reconstruction route. Ordinary `app export`, `component export`,
`sync` and `sync --push` keep their existing behavior. Native snapshots are not yet
an editable replacement for the `.w4gl`/`.wml` project layout. Graph framing and
strings are decoded and re-encoded; remaining field bodies are preserved verbatim,
not fully interpreted. See [live evidence and limits](research/direct-storage-roundtrip.md).

## Export and verify

Configure ODBC using the [configuration guide](config.md). The OpenROAD database
and ODBC database settings must identify the same source database.

```bash
gorak source export native-source --app example_app
gorak source verify native-source
```

Repeat `--app` for multiple roots. Inside a Gorak project, omitting it selects the
application folders containing `app.json`. Source includes are followed recursively;
image includes retain their filenames and remain external runtime dependencies.
Capture uses a serializable transaction with shared table locks, so schedule large
exports around active writers. It is a full snapshot, not the bounded status path.
The output directory must not already exist.

Track the complete output directory in git. It contains `manifest.json`, its
SHA-256 sidecar, `.gitattributes`, and `objects/*.srcobj`. Attributes prevent Git
newline conversion from changing native string lengths. Verification needs neither
a database connection nor XML/caches. It rejects changed hashes, unexpected files,
symlinks, invalid relationships, malformed graphs and unsupported archive versions.
Hashes detect damage; they do not authenticate the source of an archive.

## Restore a fresh clone

Prepare a disposable empty database with the matching installed OpenROAD catalogs
and an ODBC account authorized to write them. Database creation and external image
installation are separate deployment steps. Set both database options when using
a project whose configuration points at the original database:

```bash
gorak source verify native-source
gorak source restore native-source --database fresh_source --db-database fresh_source --dry-run
gorak source restore native-source --database fresh_source --db-database fresh_source
```

Restoration checks the catalog column layouts and requires empty source and
auxiliary storage tables. It locks the allocator and source tables, allocates fresh
IDs, remaps catalog references, inserts parameterized values and verifies every
stored row plus the allocator before committing. A failed write or comparison rolls
back the transaction. An existing source database is refused, including a second
restore of the same snapshot; this command cannot overwrite an application or
bypass an existing push conflict.

A successful result reports `compilation_required: true`. Compile the restored
applications in dependency order with the installed OpenROAD compiler before using
them. Compilation flags are invalidated during restore. Source restoration does not
install runtime data, external libraries, tracking extensions or runtime settings.

If the connection is lost during commit, the outcome can be uncertain. Inspect the
destination before retrying: a committed restore will fail the empty-source check.
Keep the clone as the recovery artifact; no automatic replacement or deletion occurs.

## Proven scope and remaining work

The current ASCII archive contract covers eight source catalogs and current/base
versions, with limits of 128 applications, 200,000 rows per bounded read and 256 MiB
per archive. Individual graph limits also apply. Historical versions, general
Unicode storage and other catalog layouts are unsupported. Verified deleted
dependency handles become symbolic references; live out-of-scope references fail.

The reference corpus passed a fresh-clone ODBC restoration of seven applications
and 157 components, complete independent XML comparisons before and after compiling
all seven, and six focused runtime tests. XML was only the development oracle.
This does not certify arbitrary external string/image storage references or unknown
class-field semantics. Use new corpora as controlled experiments until those layouts
are understood. Workbench visual acceptance and the full business runtime suite are
not claimed.

Normal editable sync, incremental direct writes, full field interpretation and
large-corpus changed-status latency remain separate milestones. Existing conflict
checks and explicit XML compatibility fallbacks remain in place.

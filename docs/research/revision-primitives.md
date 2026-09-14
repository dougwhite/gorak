# Revision observation and writer startup primitives

These internal Python APIs implement the first reusable portion of the verified
counter design. They are not new CLI commands, an installed revision schema or a
replacement for the full-export observation guard.

## Writer startup composition

`writer_init.compose_writer_init(existing, table, read_include=...)` accepts an
existing ING_SET-style value and an explicitly selected owner counter table.
It emits an include-file body containing the existing SET statements in order,
followed by table-specific MVCC/shared initialization. It does not execute SQL,
modify environment variables, open files implicitly or overwrite the source file.

An `include` input requires an absolute path and an explicit resolver supplied by
the execution backend. The resolver must read on the host that will run OpenROAD;
remote Windows paths must never be resolved against the local checkout. Nested
includes, non-SET statements, unterminated literals/comments and multiline literals
are rejected rather than silently transformed. Table identifiers are restricted to
simple lowercase names of at most 32 characters and are owner-qualified.

Statement order and literal contents are preserved. Comments are omitted from the
new executable artifact, whitespace between lines is normalized, and existing
files remain unchanged. The scanner validates statement boundaries; Ingres still
validates each SET statement's grammar. This is not a general SQL parser.

Live acceptance exposed a startup-parser constraint: copying a semicolon followed
by a trailing comment into an include file caused connection initialization to
fail. Emitting clean statement-per-line boundaries resolved the failure. The
composer-generated file was uploaded and used via process-local ING_SET for actual
isolated OpenROAD compilation and replacement import. Both operations succeeded
with an unrelated MVCC counter update held, and the reader saw committed values.
A control without the counter-table initialization failed as expected.

Arbitrary database-specific startup precedence, encoding/transport, original
include-file resolution on remote hosts, atomic artifact publication and lifecycle
are responsibilities for the upcoming backend integration. No existing client is
reconfigured by these functions.

## Bounded counter samples

`revision_observation.observe_revisions(settings, table, limit=4096)` reads the
explicit owner table's server_id, session_id and revision columns. It sets
MVCC/shared on that table, requests at most limit+1 rows, and fetches in chunks of
at most 256. The supported limit range is 1–100,000.

A complete `RevisionSample` contains a canonical sorted tuple of lanes. Over-budget
samples deliberately contain `lanes=None`; no truncated vector is available for
reuse as a token. Malformed or duplicate identities, nonpositive/non-bigint
revisions and invalid lookahead rows fail. Cursor/engine cleanup happens on errors.
The reader performs no installation, source mutation, pruning or acknowledgment.

Live acceptance used three owner-table counters and a concurrent uncommitted
update. A budget of two returned no usable sample. A budget of three returned the
old committed values while the writer remained active; committing the writer
changed the next sample. The temporary table was removed and existing tracking
remained healthy.

This bounds returned data and client memory, not total database query cost. It
contains no database generation binding or schema/coverage certification. The
caller must establish those before interpreting equal samples as a valid source
observation. The current two-field lane identity remains experimental pending
multi-server/restart acceptance. Do not use this API to claim restore continuity.

## Validation and next integration

Automated tests execute the production SELECT against a SQLite FIRST adapter and
cover empty/exact/overflow windows, multiple chunks, malformed lookahead, duplicate
identities, lane reuse increments and connection failure. Startup tests cover
include resolution, statement/literal preservation and unsupported input rejection.

Next: define and validate the optional schema/upgrade and startup artifact lifecycle,
then connect samples to the diagnostic snapshot protocol with generation binding.
Retain the full reference until continuity and invalidation are certified. Normal
status/sync behaviour remains unchanged.

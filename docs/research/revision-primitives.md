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

## Execution-host artifact lifecycle

`writer_artifact.writer_environment()` is an internal context manager for launchers.
It yields a copied child environment with a generated `ING_SET_<SOURCE_DATABASE>`
include. Database scoping is deliberate: a run application can open runtime databases
that do not contain the revision extension. General `ING_SET` and other environment
values remain unchanged. This setting is database-name scoped, not vnode scoped;
connections to another installation using the same database name need separate
acceptance before this can be a general launcher policy.

The caller supplies the execution host's environment and startup encoding. Nonempty
database-specific process values win; absent or empty values fall back to the
installation symbol through that host's `ingprenv`. A callback remains injectable
for controlled tests or execution-host adapters. Includes are read on
that host with a 1 MiB budget and strict decoding. Invalid input fails before the
child launches. The normalized SQL retains existing SET statements and appends the
revision table's MVCC/shared setting. Output uses exclusive creation in a unique
operation directory, strict encoding, no BOM and a bounded include path. On POSIX,
the directory/file modes are 0700/0600; Windows access follows the chosen temporary
root's ACL, which the launcher must secure.

The child must terminate before leaving the context. Normal completion and Python
exceptions remove the generated file and directory. The original include and input
environment are never rewritten. Abrupt host/process termination can leave orphaned
files; orphan recovery remains a backend responsibility. Startup contents are not
added to regular source or diagnostic artifacts.

This primitive resolves installation symbols but does not deploy a remote worker,
verify extension health, or change any normal run/import command. It must
execute on the OpenROAD host: an SSH client must not resolve remote paths locally.
General launcher wiring is pending. Preserving effective configuration requires
checking both process settings and Ingres installation symbols; reading only the
process environment is insufficient. Actian documents the separate
[installation and local settings](https://docs.actian.com/actianx/11.2/FormAppDevUser/Using_Logicals_2fEnvironment_Variables.htm)
and [database-specific startup variable](https://docs.actian.com/actianx/12.0/SysAdmin/ING_SET_DBNAME.htm).

Live Windows acceptance used the exact artifact/composer modules in a disposable
Python harness around OpenROAD import, fresh-process compilation and cleanup. A
pre-existing database-specific include was preserved, while general `ING_SET`
retained the site's session settings. Generated include paths containing spaces
worked. Both source operations completed while a separate MVCC transaction held a
counter row uncommitted; the bounded reader returned its old committed value.
Generated artifacts were absent after each child exited, and original startup file
bytes were unchanged. The test app, extension and remote harness were removed;
parent tracking identity and structural checks remained healthy. This acceptance
used an explicit process setting, not installation-symbol fallback, and does not
certify startup precedence on other OpenROAD versions or runtime database flows.


## Effective startup lookup

The default `writer_settings.installation_startup_value()` fallback queries exactly
one database-specific symbol using `ingprenv` under the child's absolute `II_SYSTEM`
(bin, then utility). It never searches PATH or requests a complete environment dump.
The same child environment is passed to the utility. Nonzero exit, stderr, timeout,
missing executable, invalid encoding and malformed output prevent artifact creation;
they never silently mean "unset". A successful empty output is the unset case.
Errors omit captured startup SQL, which may contain sensitive literals.

Actian documents that [ingprenv reads the installation symbol table](https://docs.actian.com/actianingres/12.1/CommandRef/ingprenv_Command--Display_Environment_Variable_V.htm),
so it is a fallback rather than a replacement for process-environment resolution.
Environment-name matching is case-insensitive on Windows and case-sensitive on
POSIX. Ambiguous case variants in a Windows input mapping are rejected.

Live Windows SQL acceptance confirmed a database-specific installation timeout of
17, a process override of 23, and fallback to 17 when that process override was
empty. The prior artifact implementation incorrectly treated empty as an explicit
blank; that behavior is corrected and regression-tested. Temporary installation
settings were scoped to the research database, removed afterward, and the original
symbol-table bytes matched their pre-test hash. An attempted private `II_CONFIG`
redirect did not isolate `ingprenv` on this host; that attempt stopped before utility
writes. No private-directory isolation is claimed.

The default resolver also passed real OpenROAD import and fresh-process compilation
with an installation-symbol include, an empty process override, paths with spaces
and an unrelated counter row held uncommitted. The original include and installation
symbols were restored, generated startup files were removed, and the test app and
extension were removed. Existing parent tracking remained healthy.

Remaining launcher integration must select the matching OpenROAD executable, apply
runtime overrides before resolution, keep the child inside the artifact lifetime,
and execute resolution on the remote host for SSH. This API alone does not validate
subsequent application-issued SET statements, runtime database transitions, capture
coverage or continuity, and cannot enable fast status.

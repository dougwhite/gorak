# Direct storage round-trip replacement

## Delivery boundary

The acceptance corpus is the complete private reference project. The destination
must be reconstructible from a fresh git clone through direct table encoding,
without XML import/export, original database access or ignored caches. XML remains
an independent development oracle. See the [milestone ledger](../demo/milestones.md).
Unknown coverage outside this corpus may be reported explicitly for later testing.
No reference database mutations are part of the experiment; writes use disposable
applications and databases. CLI compile/run/oracle checks do not claim visual
Workbench acceptance.

## Lossless graph framing (2026-09-14)

`storage_graph.py` adds a reader and writer beneath the class-specific semantic
reader. It consumes the complete ASCII graph envelope, object count, class names,
object identities and serialization versions. String fields retain the distinction
between null and empty and consume their declared lengths, including embedded
record/end markers. Other field data remains explicitly **uninterpreted**: numeric
references, packed compiler arrays, nullable-value encodings and bitmap data are
preserved verbatim. This is a framing codec, not a complete semantic decoder.

The writer recalculates edited string lengths and revalidates the entire envelope.
It rejects invalid headers, injected record delimiters, inconsistent counts and
out-of-budget graphs. The separate limits default to 64 MiB per graph, 100,000
objects and one million strings; existing procedure-status budgets are unchanged.
Unicode length semantics are not inferred from ASCII observations.

A read-only reference-corpus capture contained seven applications, 230 entity rows
(base/current rows included), 111 encoded graphs and 69,610 chunks, totaling
124,497,555 characters. Kinds include application, class, frame, procedure, global
and constant source; not every kind has an encoded graph. All eight captured
procedure graphs passed the earlier semantic procedure reader.

All 111 graphs passed exact character-for-character decode/re-encode comparison:
15,330 object records across 68 classes. The largest graph contained 24,402,880
characters and 2,252 objects. On one local run, decoding all captured graphs took
3.032 seconds; encoding with full framing revalidation took 3.173 seconds. The
largest graph took 0.584/0.609 seconds respectively. These are offline whole-corpus
codec measurements, not status latency, database restore or concurrency acceptance.
Private source, names, row identities and raw captures are not tracked fixtures.

Synthetic tests cover exact round trips of previous procedure fixtures (including
unsupported compiler pools), delimiter-bearing strings, null/empty distinctions,
opaque image/nullable data, explicit script edits, malformed framing, budgets and
large payloads. Unsupported semantic layouts remain unsupported by normal status.
Framing success never authorizes a table write or certifies safe ID remapping.

## Remaining table contract

Reconstruction needs more than `ii_srcobj_encoded`: entity/base/version/folder rows,
component/application metadata, ordered includes, long remarks, external storage,
and source/dependency relationships must be accounted for. Inspected catalogs also
include `ii_id`, `ii_dependencies`, `ii_app_cntns_comp`, `ii_rel_cncts_ent`,
`ii_sequence_values` and `ii_locks`. Allocation, source ownership, derived compiler
state and transient locks must be distinguished through controlled experiments;
blindly copying these tables is not an established restore protocol.

Next gates are isolated transactional allocation/reconstruction probes, complete
class-field/reference meaning, portable representation and edit ownership, then
fresh-clone restoration and subsequent conflict-safe sync. No normal import/export
route has been switched by the framing codec alone.

## Catalog archive and isolated reconstruction

`storage_archive.py` validates a bounded ASCII archive of entity, component,
application, include, source-chunk, long-remark, dependency and containment rows.
It requires complete current/base pairs, matching metadata and source graph kinds,
contiguous chunks, unique identities and resolved catalog references. Schema/type
changes, unknown tables and unresolved IDs fail explicitly. Catalog ID remapping
leaves graph-local IDs unchanged. Graph bodies still preserve uninterpreted fields.

The Ingres terminal monitor strips newlines from ordinary multiline SQL literals.
A failed synthetic reconstruction exposed this as truncated source, rather than a
missing relationship. The exact ASCII hexadecimal literal renderer prevents that
rewriting and source text injection into SQL/monitor commands. Parameterized ODBC
writers should preserve values directly instead of using this transport encoding.

A procedure-only fixture and a mixed fixture with two frames, one class and two
procedures passed direct reconstruction after removing the original disposable
application. A fresh local git clone supplied the table archive; new entity IDs
were allocated transactionally through `ii_id`. Complete XML signatures matched,
fresh-process compilation preserved source, and the harmless starting procedure
ran. Rolling back restoration preserved source absence, allocator value and managed
revision counters. Temporary apps, helpers and revision extensions were removed.
These fixtures do not certify concurrent direct saves or graphical interactions.

## Complete reference-corpus restore experiment

Following base/current IDs and source includes, rather than comparing folder names
case-sensitively, expanded the initial capture to the actual current corpus:
**seven applications, 157 components, 328 entity rows, 153 encoded graphs and
69,937 chunks containing 125,034,939 characters**. Additional kinds include 3GL
procedures, a script component and a ghost frame. Base/current name case differences
are preserved. The initial 111-graph framing result above was an incomplete
name-selected inventory, not the final coverage boundary.

The corpus also contained 115 dependency edges pointing to ten deleted entity IDs.
The private restore experiment retained their application/component names and
provenance but changed the stale destination handles to zero, preventing accidental
binding to newly allocated objects. This normalization was experimental: the archive
validator itself still rejects unresolved nonzero IDs. Live external IDs must not
be treated as stale without checking the source catalog.

A new standard database was created with Ingres/OpenROAD catalogs using
`createdb TARGET -no_x100 -f ingres windows_4gl`; see the
[official catalog creation options](https://docs.actian.com/ingres/11.0/CommandRef/createdb_Command--Create_a_Database.htm).
All archive table layouts matched and source tables were empty before restoration.
The private archive was committed to a local temporary repository and restored from
its fresh clone, with new destination entity IDs. **No XML import was used in the
reconstruction path.** Direct table insertion took 28.601 seconds in one sample.

All seven complete application XML signatures matched independent original-database
exports. All seven applications then compiled in dependency order in fresh OpenROAD
processes, with zero error diagnostics; all seven source signatures still matched
after compilation. Compilation samples ranged from 0.824 to 19.516 seconds per app.
XML was used only as an independent oracle. The source database was not compiled or
modified. This proves an experimental full-corpus source reconstruction, not normal
CLI integration, a full semantic decoder, runtime test coverage or visual acceptance.
The single large research archive is not the final git source layout.

## Native CLI integration and acceptance

`gorak source export/verify/restore` now packages this contract as an experimental
ODBC route. Captures follow case-insensitive application names and base/current IDs
under shared serializable table locks. Known stale dependencies become symbolic
only after checking that their destinations do not exist anywhere in the catalog;
live external handles fail. Restoration requires an empty destination, checks
column layouts, locks and allocates IDs, invalidates compilation, inserts bound
parameters, and compares complete stored rows and the allocator before commit.
Existing-source replacement is explicitly refused.

The partitioned archive contains native graph files, catalog metadata, hashes and
Git attributes protecting exact newline bytes. It needs no XML or ignored cache.
The new CLI exported the complete corpus in 52.207 seconds. From a fresh private
local git clone, offline verification took 8.057 seconds, destination dry-run took
14.659 seconds and parameterized ODBC restoration took 99.686 seconds. These are
single end-to-end observations with repeated defensive validation, not throughput
guarantees or incremental-status measurements.

All seven restored source signatures matched the original independent XML oracles.
All seven then compiled without errors, and all seven signatures still matched.
A focused runtime class executed six tests with zero failures, errors or skips.
The temporary test-selection constant was reset and recompiled, and its complete
application signature matched again. The full business suite and GUI acceptance
were not run. No reference-database source mutations were made.

Manifest hashing and Git newline attributes were finalized after the live ODBC
restore; archive payload equality and fresh-clone verification cover that packaging
change separately. See [native command scope](../native-source.md). General semantic
field decoding and ordinary editable sync remain incomplete.

Final packaging acceptance preserved all 153 graphs through a fresh git clone with
`core.autocrlf=true`. Both newly created destination databases and the temporary
remote helper were removed. The earlier isolated tracking installation retained
its identity and healthy checks, with its temporary extension absent.

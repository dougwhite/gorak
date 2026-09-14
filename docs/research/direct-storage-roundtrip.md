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

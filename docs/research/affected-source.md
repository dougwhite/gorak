# Bounded affected-source selection

The reader is implemented in `affected_source.py`. It is a building block; the
opt-in procedure observation layer additionally requires guarded metadata and
full-XML enrollment before reusing unaffected hashes.

A checkpoint may remember the maximum committed event ID alongside a complete
managed revision vector. A later reader computes the sum of nonnegative per-lane
increments, including new lanes. Each increment represents one transactional insert
into `gorak_change_events`. It fetches at most that count plus one event above the
saved maximum and accepts the range only if the returned count agrees exactly.

This does **not** treat allocation order as commit order. Every event above the old
maximum must be a new insert under the append-only, non-reused sequence contract.
If a lower allocated ID commits late, its increment is present but its event is
missing from the range: the count disagrees and a full comparison is required.
Pruned new events likewise cause fallback. Reset/missing lanes, generation changes,
partial vectors and changes above 4096 events are rejected before querying source.
Both old and new object IDs are retained, with a 128-object limit. Shared string,
Unicode-string and bitmap storage request full comparison until ownership is known.

Callers must bind the maximum and vector to the same verified snapshot, check
installation definitions, and bracket all candidate/source reads and publication
with unchanged complete vectors. This reader alone provides neither a semantic
snapshot nor ownership/type resolution. It writes no source, receipts or cursors.
Database sequence reuse/restart requires generation rotation under the managed
contract. Existing conflict checks and normal full-refresh behavior are unchanged.

## Verification (2026-09-14)

- Automated: exact range, locally ordered results, both identity sides, late lower
  IDs, missing/pruned events, racing extra rows, rollback/no delta, lane changes,
  generation changes, duplicate/invalid events, shared storage and event bounds.
- Isolated live database: one synthetic journal event selected with a matching
  increment; a previously allocated lower ID inserted afterward rejected with
  `event_count_disagrees_with_revisions`. Temporary revision extension and synthetic
  rows were removed. No source tables were written directly.
- Full suite: 774 tests passed; Ruff and strict mypy passed.

The [procedure observation follow-up](changed-procedure-acceptance.md) resolves
bounded current identities, checks complete metadata and decodes supported source
against the XML oracle. That layer owns dirty checkpoint reuse and its separate
latency evidence. The candidate reader alone cannot authorize it.

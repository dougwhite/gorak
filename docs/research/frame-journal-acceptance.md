# Frame and long-source journal acceptance

Checkpoint: 2026-09-14. A temporary application was created in the isolated research
database from the repository's complex-frame fixture application. The generated
schema-v2 tracking installation, actual OpenROAD XML imports/exports over SSH, ODBC
journal consumer and application mapper were used.

The temporary application included the fixture's frames, procedure and class.
Only core and the isolated included application were retained as dependencies.
No original application source was edited.

## Results

| Operation | Events | Encoded-object events | Application mapping |
|---|---:|---:|---|
| Create fixture application | 93 | 66 | Temporary application only |
| Replace application with a changed frame field label | 175 | 131 | Temporary application only |
| Replace with an approximately 84 KB procedure comment added | 224 | 180 | Temporary application only |
| Replace with embedded frame image nodes removed | 273 | 229 | Temporary application only |
| Delete application | 131 | 114 | Deleted application resolved from captured ancestry |

The remaining events came from entities, components, applications and includes.
Fresh exported XML semantic signatures differed after each requested edit.
All complete event batches mapped without requesting full comparison.

No events occurred in ii_stored_strings, ii_stored_nstrings or ii_stored_bitmaps.
The embedded image and long script changes were captured through encoded-object
storage in these operations. An embedded image is therefore not evidence that the
separate stored-bitmap path was exercised.

This probe consumed up to 10,000 events per phase so that complete observed batches
could be inspected. Most replacement operations exceeded the ordinary diagnostic
limit of 100. A full batch at that limit must continue to trigger full fallback;
a small application is not evidence that all its invalidations fit in one batch.

Whole-application replacements generated broad delete/insert activity. These counts
do not measure the event cost of a Workbench field save or isolated component edit.
They also do not establish trigger overhead: no uninstrumented timing control was
run. Event growth alone cannot be interpreted as a source-change count.

## Shared-storage corpus inventory

A separate read-only count found three stored-string rows and three stored-nstring
rows in the available reference source database, and no stored-bitmap rows. The
isolated original corpus had no rows in any of those three tables. No payloads or
reference source were changed.

Consequently, the fixture corpus cannot certify the separate shared-storage save
paths. The mapper must retain full fallback for all three table types until their
reference relationships and real save behavior are established. Existing mapper
regressions cover colliding entity IDs in these shared-storage events.

## Scope and remaining acceptance

This is live OpenROAD XML import acceptance, not Workbench GUI save acceptance.
Outstanding cases include:

- Direct frame field/script saves in Workbench rather than whole-app replacement.
- Stored Unicode/string and bitmap creation, replacement and deletion through
  actual OpenROAD save operations.
- Rename, move and version operations, including old/new ancestry.
- Large transactions spanning multiple consumer batches and concurrent saves.
- Reference ownership for shared storage before narrowing its full fallback.

The temporary application and tracking tables/rules/procedure/sequence were
removed. Installation checks confirmed no test tracking objects remained. Raw
JSON event summaries, input/output XML and logs were retained locally outside
version control.

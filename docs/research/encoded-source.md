# Direct source storage and deferred compilation investigation

Research checkpoint: 2026-09-13. These observations describe the inspected OpenROAD
12 repository, not a supported serialization contract or completed decoder.

## Findings

The source table is `ii_srcobj_encoded` (not `ii_src_obj_encoded`). Columns:

| Column | Type |
|---|---|
| entity_id | integer |
| sub_type | smallint |
| sequence_no | integer |
| text_string | varchar(1790) |

The inspected demo contains 140 chunks for 36 encoded entities, totaling 210,767
characters. Observed subtype was 1. Chunks contain a textual object graph: class
names, numbered objects, length-prefixed strings, and separators. Frame examples
include field-class names and base64-looking values. Complete grammar, string
encoding rules, reference resolution, and version compatibility remain unproven.

Related tables include `ii_entities`, `ii_components`, `ii_applications`, and
`ii_incl_apps`. Additional string/image storage exists in `ii_stored_strings`,
`ii_stored_nstrings`, and `ii_stored_bitmaps`. Their coverage and references must be
established before claiming a complete source fingerprint. `ii_encodings` is a
separate table and was empty in the demo inspected.

## Compilation probe

A disposable application containing one integer-returning procedure was imported
with `backupapp in -xml -nabort`, without `-f`:

| Step | Encoded characters | current_make | alter_count |
|---|---:|---:|---:|
| Import without forced compilation | 287 | 0 | 1 |
| Run through rundbapp | 287 | 0 | 1 |
| Explicit compileapp | 783 | 3 | 2 |

The run trace confirmed the procedure was fetched; the process returned success.
The unchanged stored form after running is consistent with runtime compilation
without persisting compiled output. Explicit compilation added an `ilobject` to the
stored graph. Therefore raw hashes can change without readable source edits.

Actian documents that omitting `-f` imports components as out of date, for compilation
on a subsequent compile or run. Forced compilation does not prevent a component
with compilation errors from being loaded; it remains out of date.
See [Import an Application](https://docs.actian.com/openroad/11.2/WorkbenchUser/Import_an_Application.htm).

Gorak currently adds `-f` for component imports and explicitly invokes `compileapp`
for nonempty application imports. A future deferred-compilation option is supported
by the documented import behavior. It must distinguish source verification from
compilation success. Running a suite must not be assumed to validate every component
in every app: unused components and includes require explicit acceptance tests.

## Performance observations

Individual measurements, not guarantees:

- Demo ODBC connection: 0.031 seconds.
- Fetch all demo encoded rows: 0.0028–0.0030 seconds.
- Larger source database: 71,948 encoded rows, 128,524,414 text characters, 1.11 seconds
  to fetch the entire encoded table. This includes more than the exported project.
- Seven project applications: 69,610 encoded rows, 124,497,555 characters; fetching
  took 1.07 seconds and local SHA-256 hashing 0.24 seconds. Adding a current-version
  filter did not reduce this sample. Whole-project raw hashing therefore misses the
  sub-second target for this corpus; candidate selection or server-side tokens are
  needed. The candidate query using server-side ordering failed with a database
  internal insertion error; fetching unsorted and ordering locally succeeded. This
  query behavior needs investigation before production use.
- Status sample: 5.10 seconds, mostly remote application exports. Earlier samples on
  the same VM were about 2.1 seconds; runtime variability is material.
- Test sample: 0.83 seconds for request upload, 5.43 seconds for the SSH/PowerShell/
  OpenROAD invocation. These timings do not isolate PowerShell startup from OpenROAD.

The test runner calls subprocess directly and currently bypasses the SSH session
options used by the source transport. Sharing those options is a small follow-up;
measuring helper startup and OpenROAD runtime separately is still required.

## Recommended implementation path

1. Use direct ODBC reads, preserving exact values, explicit ordering, and length
   boundaries in fingerprints. Establish current-version/entity mappings and scope
   requests to the tracked applications.
2. Fingerprint encoded objects plus all relevant source metadata and referenced
   storage. A matching fingerprint can avoid OpenROAD startup; a mismatch must
   trigger semantic comparison, because compilation changes encoded bytes too.
3. Bind fingerprints to the target and to verified XML baselines. Obtain consistent
   snapshots or bracket baseline creation with checks; fail closed on incomplete
   queries, duplicate/missing chunks, target mismatch, or concurrent changes.
4. Add controlled probes for description/include edits, component/app deletion,
   no-op saves, Unicode, images, complex frames, and version changes. The larger
   exported project is a useful private corpus; do not commit it or its raw extracts.
5. Implement deferred compilation explicitly, then verify test-run diagnostics and
   the behavior of unused invalid components before making it the development default.
6. Decode source graphs incrementally only where useful. Keep XML fallback for
   unsupported forms. Direct database source writes are outside this proposal.

Sub-second no-change checks look feasible from the direct-read measurements. A
sub-second import-and-test loop is not established by this investigation.

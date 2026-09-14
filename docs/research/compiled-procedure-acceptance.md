# Compiled-procedure CLI acceptance

2026-09-14 follow-up to [changed-procedure acceptance](changed-procedure-acceptance.md).
The owner was away from the desk and explicitly requested CLI substitutes for the
Workbench steps. **These results are CLI acceptance, not manual Workbench acceptance.**
No desktop session or launcher was required.

## Reader scope

`encoded_graph.py` replaces fixed-prefix extraction with a bounded object reader.
It reads object IDs, serialization versions, length-delimited strings, source and
symbol references, and record/end markers. Source comes from the procedure's script
reference, not the first string found or an assumed object position. The existing
ASCII, 1 MiB and chunk limits remain; graphs are capped at 512 objects.

Supported compiler records are the observed `ilobject`, `scopesymtab`, `symfrmvar`
and simple integer `symvariable` forms. Packed integer arrays are checked against
row/column counts, encoded byte lengths (including line wraps), and complete numeric
encoding. Symbol buckets/chains must resolve without missing IDs, duplicates or
cycles, and the compiled name must agree with the current entity. Unknown schemas,
classes, extra fields, literal pools and unsupported symbol types request XML.
This validates the supported storage layout; it is not an IL interpreter or compiler
correctness checker.

Three synthetic compiled fixtures cover integer returns 0 and 1 and a local integer
variable. Their complete reconstructed component signatures match fresh XML exports.
A fourth compiled fixture with a string literal pool records an explicit unsupported
case. All fixture source is synthetic; no database IDs or machine settings are
included. Numbered IDs inside the graph are required serialization-local references.

Compilation also changes `ii_components.value_type` from blank to `system` for the
observed scalar, nonnullable integer procedure. The metadata guard normalizes only
that pair, only for integer/N/non-array/non-read-only rows with an empty value string.
Other types, classifications, defaults and metadata changes remain guarded. This
is a narrow experimentally verified equivalence, not permission to ignore the column.

## CLI experiment

A temporary revision extension and helper deployment were installed in an isolated
source database. The sequence used OpenROAD XML import, `compileapp -f -e`, Gorak
status and separate full-reference verification. The compiler's force option makes
unchanged components recompile; see [Actian's CompileApp documentation](https://docs.actian.com/openroad/6.2/WorkbenchUser/Compile_an_Application.htm).

| First status following operation | Fresh CLI time | Observation |
| --- | ---: | --- |
| Initial compilation of enrolled uncompiled source | **0.381 s** | ODBC refresh; no source changes |
| Forced recompilation | **0.387 s** | ODBC refresh; no source changes |
| XML replacement with edited description/script, then compilation | 1.188 s | Explicit identity fallback; correct pull |
| Forced recompilation of the edited source | **0.393 s** | ODBC refresh; correct existing pull retained |

Every row agreed with a separate full-XML semantic inventory and three-way plan.
XML verification was outside the timed status. A divergent disk edit was classified
as conflict; real push preflight failed with exit 1 and an unchanged revision vector.
A compiled literal-pool example explicitly required XML. Temporary applications,
revision extension and helper directories were removed after the runs.

These are small isolated samples, not tail latency or large-corpus guarantees.
Existing counter bounds, generation/target/scope binding, non-sliding oracle expiry,
concurrency checks, quarantine and mutation-time conflict checks are unchanged.
No direct SQL writes to source tables were used. `GORAK_SOURCE_DECODING=procedures_v1`
remains the opt-in; enrollment is still limited to 128 current procedures.

## Workbench checks deferred until the owner returns

- [ ] Start from a compiled procedure; save only its description, measure the first
  status and compare the complete result with XML.
- [ ] Save a script edit through Workbench and verify whether its save preserves or
  replaces compiler records; measure the first status and compare with XML.
- [ ] Recompile through Workbench and verify source remains unchanged through ODBC.

Use a copy of the owner's actual working Workbench launcher, preserving its launch
environment and adding only the isolated revision setting. The CLI replacement path
changes identities, so it cannot certify Workbench save behavior. The prior manual
uncompiled-procedure results remain valid historical evidence, not new compiled-save
acceptance.

Final automated checks: **842 tests passed**, Ruff passed, and strict mypy passed.
A final independent read verified that the temporary app/extension were absent and
the original parent tracking identity and structural health were unchanged.

# Compatibility fixtures

`project/` is independently authored synthetic source for downstream compatibility
tests. It contains no connection settings or native XML cache. Copy it into a
temporary directory before editing or reconstructing it.

It exercises application includes, procedure and user-class metadata, methods,
frame scripts, explicit geometry/field state, Unique Style (`fieldstyle=0`), a
typed table-column prototype and viewport content, and an invalid XML character instruction.
It also covers saved queries, PNG references, class icons, cursors, ordered macros, an absent frame stylesheet, external libraries, field templates, qualified types and dollar attribute names.
The button's actual colour is `6`; the project/application/frame creation-style
colours are `6`/`7`/`8`. Existing fields must never inherit the frame palette colour.

`duplicate_names` deliberately contains name collisions; consumers must preserve
all fields even though native compilation rejects that frame.
Repeated toolbar sections preserve multiple bars on each of the four sides.
WML omits `DV_SYSTEM` (`defaultvalue=1`); the fixture also preserves explicit `DV_NULL` and `DV_STRING` modes.

These cases are reconstruction and tooling inputs, not a runnable acceptance
application or proof of full OpenROAD language/Workbench coverage. Consumers should
assert behaviour appropriate to their role: LSP bindings and locations, designer
field state and source-preserving edits, extension schema acceptance. Reading the
files without asserting their meaning is not a compatibility test.
For query sidecars, readers should accept the format and source-editing tools
should preserve it; query authoring or query-expression navigation is not implied.

Consumers pin a gorak commit containing the manifest and fixtures. An update PR
changes that pin and runs their local compatibility checks. Fixture fixes and
additions may occur without a contract bump when the represented rules are unchanged.

Source contract 11 adds PRIVATE/default clauses on attribute declarations and structured
attribute/method values with a declaration string, remarks and ordered member tagged
values. Consumers must read declaration from either the string or structured form;
source-editing tools must preserve the other fields and duplicate tag names.

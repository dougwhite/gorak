# Compatibility fixtures

`project/` is independently authored synthetic source for downstream compatibility
tests. It contains no connection settings or native XML cache. Copy it into a
temporary directory before editing or reconstructing it.

It exercises application includes, procedure and user-class metadata, methods,
frame scripts, explicit geometry/field state, Unique Style (`fieldstyle=0`), a
typed table-column prototype, and an invalid XML character processing instruction.
The counter class has a saved query with a table, typed column and select target
in an adjacent `.queries.json` file (sidecar schema version 1).
Source contract 3 adds a small RGBA PNG used by both application and frame icons
and the frame background, plus an ordered class-icon collection in
`counter.icons.json`. Consumers should resolve application-relative `images/`
references, preserve alpha and sidecars, and retain shared references when editing.
Native bitmap metadata, when exported, accompanies the PNG as `.png.bitmap.json`;
PNG-first assets need no metadata.
The button's actual colour is `6`; the project/application/frame creation-style
colours are `6`/`7`/`8`. Existing fields must never inherit the frame palette colour.

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

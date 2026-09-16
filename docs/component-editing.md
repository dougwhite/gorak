# Editing readable OpenROAD source

Gorak reconstructs the established compact source from readable files, checks the current database
against its export baseline, imports transient XML,
and verifies a fresh full export. XML baselines protect synchronization; they do
not supply application source. Managed revision/direct decoding remain optional.

## Current editable surface

Classes, 4GL procedures, globals, 3GL declarations, shared scripts, ghost frames,
normal frames and constants have supported readable representations. Scripts,
metadata, class attributes/methods and tagged values are editable. Query-designer
metadata is unsupported and is omitted on export and import. Component deletion pushes remain unsupported.

Frame `.w4gl` contains the frame script, metadata and only its field-default
overrides. Root defaults are authoritative, application JSON overrides the root,
and frame `[fielddefaults]` overrides the application. `.wml` contains directly nested controls, property overrides and field
events. Controls can be added, removed or reordered. Keep field names unique and
scripts consistent with their scopes. Omitted properties are reconstructed from inherited field defaults.

Unknown types/properties, incompatible row types and ambiguous structures fail
explicitly. All supported exported types can be recreated from a clean clone.
Newly authored source still needs valid OpenROAD semantics and installed external
dependencies. See [file format and migration](files.md) and [push](push.md).

## Frame coordinates and verification

OpenROAD describes field coordinates in thousandths of an inch ([XLeft](https://docs.actian.com/openroad/6.0/LangRef/XLeft_Attribute.htm)).
The rehearsed Windows OpenROAD 12 import/export path converts them to a 96-unit
logical pixel grid: for example, 321 exports as 323, 730 as 729, and 1100 as 1104.

Import verification permits only exact logical-pixel equivalence of `xleft`,
`ytop`, `width` and `height` in frame form fields. It is not a general numeric
error tolerance. Supported scripts, metadata, inherited defaults and layout must round-trip
through the readable contract. Encoded bitmap XML line wrapping is normalized. Baseline-versus-current database conflict checks remain fully exact.
A verified geometry conversion stages the canonical exported WML with the new
baseline, so the next status does not show an endless local change. Review this
WML in your Git diff. Geometry behavior on other execution platforms has not been
certified. Unexpected conversion still stops verification and retains evidence.

Helper version 9 imports source without forcing compilation. Push verifies and
installs all source before compiling; a compiler error is reported separately and
does not require recovery, but the push command exits nonzero.
`gorak compile APP [COMPONENT]` compiles current database source and displays full
diagnostics. Import/verification failures retain the
operation evidence and can be retried or reconciled as described in [push](push.md).

## Evidence and remaining acceptance

The compact-source importer decoded all eight observed component types. A fresh
private clone imported and compiled seven applications in a fresh disposable
database. Two subsequent export rounds matched all 181 readable files byte for
byte, with clean status and no-op pushes. These checks do not certify unsupported
query metadata or other unrepresented designer metadata. Explicit NULL attribute defaults
are preserved in compact declarations as `DEFAULT NULL`.

After recovering omitted NULL initializers from retained exports, the imported
application suite reported 444 tests, zero failures/errors and three skipped.
Old files that omitted those initializers need an authoritative re-export to
recover them; inference from the datatype alone is insufficient. Visual Workbench acceptance
has not been performed. Restart Workbench if its compiled component cache shows
an older version.

### Ambiguous field styles

Optional `gorak_style="N"` selectors preserve omitted values when multiple styles
of the same type differ. See [numbering and precedence](files.md#field-defaults-and-wml).
Historical ambiguous WML fails before writes until a known selector is supplied
or the source is re-exported authoritatively. This qualifies the compatibility
claim alongside the separately documented missing NULL initializers.

Focused mocked tests check the two-style colour/header case, inherited and explicit
overrides, harmless multiple styles, invalid selectors, existing-component
comparison/import and rejection of changed properties despite identical projections.
A focused disposable live probe imported an authoritative two-style tablefield
export; it retained colour 5 and disabled header buttons, produced two identical
re-exports, and finished with clean status and no-op pushes. Existing-component
imports then selected style 1 with an explicit colour override (7, headers enabled)
and restored style 2 (5, headers disabled), ending with clean status. OpenROAD omits the
native zero-valued header flag from XML. An initial minimal authored probe was
rejected because OpenROAD supplied additional native defaults; its artifacts were
retained, and its verification was not bypassed.

Manual Workbench visual acceptance, including the affected table control, remains
outstanding and is required before merge.

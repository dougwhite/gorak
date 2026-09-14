# Editing readable OpenROAD source

Gorak reconstructs the established compact source from readable files, checks the current database
against its export baseline, imports transient XML, compiles in a fresh process,
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

`backupapp -f` compiles before loading ([Actian import reference](https://docs.actian.com/openroad/11.1/WorkbenchUser/Import_an_Individual_Component.htm)).
Helper version 8 instead imports first and invokes `compileapp -cCOMPONENT -f -e`
in a fresh process. Import/compile failure may still leave changed source in the
database; the ordinary pending/recovery gates apply.

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

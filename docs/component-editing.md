# Editing readable OpenROAD source

Gorak reconstructs format-2 source from readable files, checks the current database
against its export baseline, imports transient XML, compiles in a fresh process,
and verifies a fresh full export. XML baselines protect synchronization; they do
not supply application source. Managed revision/direct decoding remain optional.

## Current editable surface

Classes, 4GL procedures, globals, 3GL declarations, shared scripts, ghost frames,
normal frames and constants have complete readable representations. Scripts,
metadata, class attributes/methods, tagged values and structured metadata are
editable. Component deletion pushes remain unsupported.

Frame `.w4gl` contains the frame script, metadata and only its field-default
overrides. Root defaults are authoritative, application JSON overrides the root,
and frame `[fielddefaults]` overrides the application. `.wml` contains layout, explicit properties, array wrappers and field
events. Controls can be added, removed or reordered. Keep field names unique and
scripts consistent with their scopes. New controls must specify their intended
properties; no hidden XML or inferred default style fills them in.

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
error tolerance. Scripts, metadata, opaque content and all other XML still compare
exactly. Baseline-versus-current database conflict checks remain fully exact.
A verified geometry conversion stages the canonical exported WML with the new
baseline, so the next status does not show an endless local change. Review this
WML in your Git diff. Geometry behavior on other execution platforms has not been
certified. Unexpected conversion still stops verification and retains evidence.

`backupapp -f` compiles before loading ([Actian import reference](https://docs.actian.com/openroad/11.1/WorkbenchUser/Import_an_Individual_Component.htm)).
Helper version 8 instead imports first and invokes `compileapp -cCOMPONENT -f -e`
in a fresh process. Import/compile failure may still leave changed source in the
database; the ordinary pending/recovery gates apply.

## Evidence and remaining acceptance

Format-2 reconstruction passed exact semantic comparison for 222 available
component exports spanning all eight observed types and seven application exports.
Synthetic fixture tests cover declarations, palettes, field events, typed rows,
whitespace, incompatible types and migration recovery.

A real Git clone containing no XML or cache created three applications in a new
disposable source database, compiled them and passed the configured test suite.
Script/frame edits then passed push, tests, unchanged status and a no-op push.
Repeated exports were byte-stable. A separate disposable rehearsal also verified
metadata edits across all eight types and frame coordinate canonicalization.

These are automated database/runtime checks. Visual Workbench acceptance of the
newly reconstructed frames has not been performed for this format change. Restart
Workbench if its compiled component cache shows an older version.

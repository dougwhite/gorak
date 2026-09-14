# Editing readable OpenROAD source

The XML fallback is the ordinary compatibility path. Gorak overlays readable
changes onto complete preserved XML, checks the current database against the
baseline, imports the component, compiles it in a fresh process, and verifies a
fresh full export. Managed revision and direct decoding remain optional.

## Current editable surface

The compatibility corpus contains classes, 4GL procedures, globals, 3GL procedure
declarations, shared scripts, ghost frames, normal frames and constants. Existing
components of these types can carry script changes and represented scalar metadata
changes. Class attribute/method declarations and tagged values retain unedited
native row metadata. Adding/removing declarations is different from deleting the
component itself; component deletion pushes remain unsupported.

Frame `.w4gl` contains frame scripts and metadata. Frame `.wml` contains layout,
properties and field-event scripts. Existing field properties and scripts, nested
controls, field additions/removals and sibling ordering are reconstructed against
preserved XML. Keep field names unique and scripts consistent with their scopes.
New fields with explicit `xleft` or `ytop` do not inherit palette gravity;
set `gravity` explicitly when alignment relative to the parent is intended.
Existing fields retain their native alignment.
Changing a field's name or type is interpreted as replacing that field; include
all intended properties and code in the replacement.

Field defaults are inherited from repository, application and frame layers.
Property edits to existing default styles are supported; inventing new default
style/group identities is not. Unrepresented complex XML remains in companions.
Do not turn an empty placeholder for opaque metadata into arbitrary text.
Unknown types/properties and ambiguous structures are rejected explicitly.

New procedure/class source can be authored without a companion. A newly authored
frame still needs an exported frame baseline. Portable applications can restore
other exported component types from their tracked companions. See [push](push.md).

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

Local corpus reconstruction preserved all XML content for 157 available component
baselines. Twelve frame position edits reconstructed schema-valid XML. One local
3GL declaration had no cached baseline and was excluded from that result.
These are local format checks. Separately, a synthetic application containing all
eight types was created and compiled; description edits to all eight passed one
live `gorak sync --push` with full export verification. This does not establish
runtime behavior for every component or execute an external 3GL library.

See [the current rehearsal log](demo/rehearsal.md) for live import, test, geometry,
and manual visual acceptance. Publication remains gated on a usable demo frame
and the complete repeatable feature/PR loop.

The packaged XML property-order and inheritance tables describe the installed
OpenROAD 12 export schema used for these checks. They contain protocol type/field
names rather than database storage definitions. Unobserved schema extensions are
preserved untouched or refused when their order/shape cannot be reconstructed.

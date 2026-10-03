# Files and formats

## Project layout

```text
project/
├── gorak.json
├── field_defaults.json
├── AGENTS.md
├── app_name/
│   ├── app.json
│   ├── field_defaults.json         # optional stylesheet delta
│   ├── component.fielddefaults.json  # optional frame overrides
│   ├── component.w4gl
│   └── frame_component.wml
├── .env
└── .openroad/
```

Commit the readable source, application metadata, `gorak.json`, `AGENTS.md`,
and field-default JSON.

Do not commit:

- `.env`, which contains local connection settings and may contain credentials;
- `.openroad/`, which contains local synchronization baselines, target binding,
  locks, recovery evidence, temporary XML transport, and run artifacts.

Generated `.w4gl` and `.wml` files use LF line endings on every platform;
new projects include Git attributes to retain them on Windows.

Readable Gorak source is portable without the original `.openroad/` cache.
External OpenROAD image, framework, and runtime dependencies must still be
installed in the destination environment.

## W4GL source

`.w4gl` files contain TOML metadata, an `===` separator, and readable OpenROAD
4GL source:

```toml
[classsource]
superclass = "userobject"

[attributes]
count = "INTEGER NOT NULL"

[methods]
get_count = "METHOD RETURNING INTEGER NOT NULL"

===
METHOD get_count() =
{
    RETURN self.count;
}
```

Gorak currently reconstructs these core component types from readable source:

- frames;
- 4GL procedures;
- userclasses;
- 3GL procedures;
- constants;
- globals;
- include/shared scripts; and
- ghost frames.

Unknown source shapes and unsupported authored metadata are refused rather than
silently discarded. Query Designer metadata is not currently represented.

## Frame WML

Frames use a `.w4gl` file for component metadata and script plus a `.wml`
file for layout and field event scripts:

```xml
<frame>
  <topform width="6000" height="3000">
    <buttonfield name="calculate" xleft="200" ytop="500" textlabel="Calculate">
      <script><![CDATA[on click = {
        score = CALLPROC calculate();
      }]]></script>
    </buttonfield>
  </topform>
</frame>
```

Keep WML well formed and field names consistent with their event scripts.

XML-invalid characters are stored directly in W4GL script bodies and with standard
string escapes in TOML/JSON. In WML, use `<?ingres_invalidxmlchar N?>` (`N` is the
decimal code point), inside script text or a property child element:

```xml
<defaultstring>before<?ingres_invalidxmlchar 7?>after</defaultstring>
```

## Native stylesheets and field state

Frame WML contains actual field values, including geometry and native `fieldstyle`.
W4GL and stylesheet JSON contain no source-version markers. The project root
stylesheet uses named groups and styles; older palette formats require a fresh export.
Omitted `fieldstyle`, explicit `0` (Unique Style), and positive ordinals remain
distinct. No stylesheet lookup supplies missing WML values, and `gorak_style`
is rejected in this format. Scripts and inline bitmap payloads remain in source. Column prototypes preserve
their native type as `<protofield type="entryfield" ...>`, and matrix entries
retain native `row`/`column` attributes.

Stylesheet files describe only the native Style Editor palette. Resolution is:

```text
built-in stock stylesheet → project → optional application → optional frame
```

The built-in baseline is the complete native `Core.empty_frame` stylesheet from
OpenROAD 12.0.0/21024 p16043: 30 groups, 34 entries, and 29 field types. It retains
native wrappers, duplicate entries, geometry, scripts, and inline resources.
Baseline version selection is outside this contract.

A stock project's root `field_defaults.json` is minimal:

```json
{}
```

An application may have `field_defaults.json`; a frame may have an adjacent
`<component>.fielddefaults.json`. Missing child files inherit their parent.
Normal export creates no application layer and omits empty frame deltas.
It never promotes common frame values. Older project formats must be freshly exported.

Layers contain only properties that differ from their parent. Group names retain
repeated-group labels such as `entryfield:2`. Within each group, `style1`, `style2`,
and so on identify fixed native slots, regardless of JSON key order. For example:

```json
{
    "groups": {
        "stackfield": {
            "styles": {
                "style2": {
                    "outlinecolor": "29"
                }
            }
        }
    }
}
```

This changes only the second stackfield style's outline colour. All other values
inherit. Native values are strings: `""` is an explicit empty value, `"0"` retains
native zero/false spellings, and `null` removes an inherited property or entry.
Nested properties and numbered `row1`, `row2` entries use the same inheritance.
Scripts and inline resources retain their complete text.

Complete stylesheets contain `properties` for container metadata, `group_order`
for native group order, and `groups`. Each group contains its wrapper `properties`
and numbered `styles`. `_type` records the native XML type and `_attributes`
retains XML attributes. A standalone root adds `"standalone": true` and contains
all values. Ordinary child layers omit unchanged metadata and ordering.

Structural edits are explicit: add a complete numbered style, remove an entry
with `null`, or supply `group_order` when adding/removing/reordering groups.
Resolved style numbers must be contiguous from `style1`; removing a middle slot
requires explicitly assigning the remaining slots. Gorak never renumbers supplied
style names. When a new property belongs before an inherited property in native
XML, a short hint such as `"$before": {"outlinestyle": "fgpattern"}` preserves its
position. The exceptional `$order` property lists native property names when
reordering existing XML properties. Ordinary value edits need neither hint. Literal colons and
percent signs in native group names are percent-escaped to distinguish them from
repeated-group suffixes.

`gorak styles publish` writes the complete project stylesheet. Complete roots
never consult the built-in baseline, including when resolving app/frame deltas.
`gorak styles compact --dry-run` previews promotion; `gorak styles compact` promotes
identical whole frame stylesheets to applications, and identical application
stylesheets to the project. It verifies resolved stylesheets and removes empty
child files. Partial common-property promotion is deliberately not inferred.

Stylesheet maintenance retains before-images and operation records under
`.openroad/styles/`. Older source formats and migration commands are not supported;
re-export existing applications using the current CLI.

### Designer consumers

Use `gorak styles show --app APP --component FRAME` to obtain the resolved
stylesheet and an `entries` array as JSON. Python consumers can also resolve
stylesheets through `gorak.native_styles.project_styles`, `parent_styles`,
or `frame_styles`. `entries(resolved)` exposes `(group, group_ordinal,
style_ordinal)` identities, field type, and the complete native sample. Repeated
group ordinals and style ordinals are one-based. A designer may use samples when
creating a field, but must materialise the resulting field values in WML.
Editing or displaying an existing field must use its explicit WML values.
Native `fieldstyle` is independent of these creation samples. Consumers of the old
`field_styles`/`gorak_style` contract need an update before editing native stylesheet projects.

## Application metadata

Each application has an `app.json` file. It stores:

- `starting_component`;
- `description`;
- optional `database_name` and `database_type`; and
- `included_applications`.

Core is implicit. Other included applications and external images must be
available when the application is reconstructed or run.

The root `gorak.json` describes the project and may also contain configured test
suites. See [Run and Test](run-test.md).

## Round-trip contract

Gorak's source contract is semantic readable-source equivalence:

```text
OpenROAD export → readable source → OpenROAD import → readable re-export
```

The re-exported readable source should represent the same scripts, declarations,
metadata, defaults, and layout, and remain stable through repeated cycles. Exact
byte-for-byte XML reproduction is not the contract because OpenROAD can
canonicalize its transport representation.

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

New frame `.w4gl` files declare `source_format = 3` before `[framesource]`.
Their WML contains actual field values, including geometry and native `fieldstyle`.
Omitted `fieldstyle`, explicit `0` (Unique Style), and positive ordinals remain
distinct. No stylesheet lookup supplies missing WML values, and `gorak_style`
is rejected in this format. Scripts and inline bitmap payloads remain in source.

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
{
    "schema": "gorak-native-styles-v1",
    "mode": "delta",
    "changes": []
}
```

An application may have `field_defaults.json`; a frame may have an adjacent
`<component>.fielddefaults.json`. Missing child files inherit their parent.
Normal export creates no application layer and omits empty frame deltas.
It never promotes common frame values. Existing legacy root files must be migrated
before native export, rather than being silently reinterpreted.

A complete layer has `schema`, `mode: "complete"`, and `stylesheet`.
Each stylesheet node has `tag`, optional `attributes`, and either `text` or an
ordered `children` array. Attribute names use expanded XML names for namespaces.
The root tag is `fielddefaults`. Text is a string, including empty strings and
native zero/false spellings. Arrays preserve every group, property, and duplicate
style in native order. This representation includes only the stylesheet subtree.

A nonempty delta adds `parent_structure` and a `changes` array. Each change has
`path` (string object keys and zero-based array indexes) and `value` (replacement).
Paths target exact native positions, never a matching or closest style. Replacing
an ordered array defines add/remove/reorder; replacing a node can remove properties
or reset them to absence. Omission inherits unchanged parent content. Overlapping
paths and paths that do not exist are rejected. The parent structure fingerprint
checks tags, native group names, types, and topology, so structural parent changes
require an explicit rebase instead of silently retargeting a child delta.

`gorak styles publish` commits the complete project stylesheet. Complete roots
never consult the built-in baseline, including when resolving app/frame deltas.
`gorak styles compact --dry-run` previews promotion; `gorak styles compact` promotes
identical whole frame stylesheets to applications, and identical application
stylesheets to the project. It verifies resolved stylesheets and removes empty
child files. Partial common-property promotion is deliberately not inferred.

`gorak styles migrate --dry-run` checks historical compact frames against retained
native XML. Migration refuses absent evidence, ambiguous compressed values, and
local state that differs from the evidence. It rebuilds organisation from the stock
project root plus exact native frame deltas, rather than interpreting legacy style
ordinals. Reconcile edits or re-export authoritative source when refused.
Before-images and operation records are retained under `.openroad/styles/`.

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
`field_styles`/`gorak_style` contract need an update before editing format 3.

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

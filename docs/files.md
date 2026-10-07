# Files and formats

## Project layout

```text
project/
├── gorak.json
├── field_defaults.json
├── AGENTS.md
├── app_name/
│   ├── app.json
│   ├── field_defaults.json            # optional application stylesheet delta
│   ├── component.fielddefaults.json   # optional frame stylesheet delta
│   ├── component.w4gl
│   └── frame_component.wml
├── .env
└── .openroad/
```

Commit the readable source, application metadata, `gorak.json`, `AGENTS.md`,
and stylesheet JSON.

Do not commit:

- `.env`, which contains local connection settings and may contain credentials;
- `.openroad/`, which contains synchronization state, locks, recovery evidence,
  temporary XML, and run artifacts.

Generated `.w4gl` and `.wml` files use LF line endings. `.w4gl` files end
with exactly one newline.

Readable Gorak source can reconstruct supported OpenROAD source without the
original `.openroad/` cache. External OpenROAD frameworks, images, and runtime
dependencies must still exist in the destination environment.

## W4GL source

`.w4gl` files contain TOML metadata, an `===` separator, and readable
OpenROAD 4GL source:

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

Gorak currently reconstructs frames and frame templates, 4GL and 3GL procedures, user classes,
constants, globals, include/shared scripts, ghost frames, external libraries and field templates.

Unsupported source shapes are refused rather than silently discarded.

Declarations support qualified types (`APP!CLASS`), `LONG BYTE`, and quoted attribute names containing `$`.

```toml
[attributes]
created = "DATE NOT NULL DEFAULT 'today'"
items = "PRIVATE ARRAY OF SHARED!ITEM DEFAULT NULL"
label = { declaration = "VARCHAR(80) NOT NULL", remark = "Display label", taggedvalues = [{ name = "column", value = "label" }] }

[methods]
lookup = "PRIVATE METHOD RETURNING SHARED!ITEM"
describe = { declaration = "METHOD RETURNING VARCHAR(80) NOT NULL", remark = "Describe this object" }
```

Declarations follow standard OpenROAD declaration syntax, including `PRIVATE`, `ARRAY OF`, `NOT NULL`, and `DEFAULT` clauses. Use a declaration string, or an object containing `declaration` when remarks or other metadata are present.

Saved query metadata lives in optional `<component>.queries.json` files.

Macro definitions use ordered tables such as `[[framesource.macro_vars]]`, with `name`,
`value` and optional `shortremark`; re-export older sources to recover omitted definitions.

External libraries use `[extlibsource]` metadata; field templates use `[fieldtemplate]`
metadata and a `.wml` layout with typed `framefield`/`reportfield` sections.

## Frame WML

Frames use `.w4gl` for component metadata and main script, and `.wml` for
layout, field properties, and field event scripts:

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

WML stores actual field state explicitly, including geometry and native
`fieldstyle`. Stylesheets are not used to fill in missing field properties.
Nested `viewfield` and `protofield` elements preserve their native class with `type="…"`.

OpenROAD characters that are invalid in XML are represented with
`<?ingres_invalidxmlchar N?>` processing instructions:

```xml
<defaultstring>before<?ingres_invalidxmlchar 7?>after</defaultstring>
```

Duplicate field names are preserved; OpenROAD compilation diagnoses qualified-name collisions.

## Native stylesheets

`field_defaults.json` represents the native OpenROAD Style Editor stylesheet,
separately from WML field state.

Stylesheets resolve in this order:

```text
built-in stock stylesheet → project → optional application → optional frame
```

A stock project normally has an empty root delta:

```json
{}
```

Application and frame stylesheet files contain only differences from their
parent. Empty frame deltas are omitted; `{"absent": true}` preserves a frame
with no native stylesheet.

Groups and native style slots use stable names such as `entryfield:2`,
`style1`, and `style2`. A simple override looks like:

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

Native values are stored as strings. `null` removes an inherited value.
Gorak also preserves native ordering, duplicate styles, scripts, nested values,
and inline resources where required for reconstruction.

`gorak styles publish` writes a complete standalone project stylesheet.
`gorak styles compact` can promote identical child stylesheets upward while
preserving each frame's resolved stylesheet. Use `--dry-run` to review the
change first.

`gorak styles show --app APP --component FRAME` prints the resolved stylesheet
and native style identities for inspection or designer tooling.

Older field-default formats and `gorak_style` are not supported; re-export
existing applications with the current Gorak version.

## Application metadata

Each application has an `app.json` file containing:

- `starting_component`;
- `description`;
- optional `database_name` and `database_type`; and
- `included_applications`.

`core` is implicit. Other included applications and external runtime
dependencies must be available when the application is reconstructed or run.

The root `gorak.json` describes the project and may also contain configured
test suites. See [Run and Test](run-test.md).

## Round-trip contract

For supported source, Gorak aims for stable readable-source round trips:

```text
OpenROAD export → readable source → OpenROAD import → readable re-export
```

OpenROAD may canonicalize its XML representation, so byte-for-byte XML identity
is not required. The reconstructed application should preserve the supported
source semantics and remain stable through repeated export/import cycles.

Image assets live in each application’s `images/` directory and use relative references:

```xml
<bgbitmap src="images/background.png"/>
```

Built-in images use references such as `src="builtin:pal_icon6"`.
Optional `path` preserves the original OpenROAD filename. Class icons use
`[[icons.entries]]` in the class’s `.w4gl` metadata.

# Files and formats

## Project layout

```text
project/
├── gorak.json
├── field_defaults.json
├── AGENTS.md
├── app_name/
│   ├── app.json
│   ├── field_defaults.json
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

## Field defaults

The root `field_defaults.json` contains repository-wide OpenROAD field defaults.
An application's `field_defaults.json` stores only differences from the root,
and a frame's `[fielddefaults]` metadata stores only further differences from
the application.

Values equal to inherited defaults are omitted from WML and reconstructed during
import.

When multiple styles of one field type imply different omitted values, Gorak may
write a `gorak_style="N"` selector:

```xml
<tablefield name="items" gorak_style="2"/>
```

The selector is a 1-based position among styles of that field type. Preserve it
unless you deliberately know which style the control should use. Gorak consumes
the selector during import; it is not sent to OpenROAD as a field property.

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

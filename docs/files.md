# Files And Formats

## Project Layout

```text
project/
├── gorak.json
├── field_defaults.json
├── app_name/
│   ├── app.json
│   ├── component.w4gl
│   └── frame_component.wml
└── .openroad/
    ├── gorak-state.json
    └── app_name/
        ├── app_name.xml
        └── component.xml
```

Commit the app folders and repo metadata. Do not commit `.openroad/`; it is a
local XML/cache/state directory.

## `.w4gl`

`.w4gl` stores component metadata as TOML front matter, followed by optional
script text separated by `===`.

```toml
[framesource]
datatype = "integer"
templatename = "standard"

===

initialize()=
{
    CurFrame.Trace(text = 'Hello');
}
```

Additional tables may appear when present in the XML:

```toml
[attributes]
Name = "VARCHAR(32)"

[methods]
Load = "METHOD RETURNING INTEGER NOT NULL"

[taggedvalues]
db_name = "demo"
```

## `.wml`

Frame visual markup is written to `.wml` beside the `.w4gl` file.

```xml
<frame>
  <startmenu />
  <topform>
    <entryfield
      name="example_entryfield"
      xleft="104"
      ytop="104"
      width="1417"
    />
  </topform>
</frame>
```

Current `.wml` coverage includes:

- `startmenu`
- `topform`
- `mainbartop`
- `mainbarbottom`
- `mainbarleft`
- `mainbarright`
- nested `childfields` / `childmenufields`
- field scripts as CDATA

## `app.json`

Application metadata lives in the app folder.

```json
{
  "starting_component": "fm_start",
  "description": "Demo app",
  "included_applications": [
    "shared_app",
    {"name": "image_include", "image": "image_include.pkg"}
  ],
  "database_name": "runtime_db",
  "database_type": "1"
}
```

## Field Defaults

New projects include repo-level defaults:

```text
field_defaults.json
```

Exports may also create app-level overrides:

```text
app_name/field_defaults.json
```

During export, frame defaults already represented by the repo/app defaults are
omitted from the frame `.w4gl`; only overrides remain.

Promote shared app-level overrides into the repo-level file:

```bash
gorak defaults flatten
```

## XML Cache

Gorak caches exported OpenROAD XML under `.openroad/`.

```text
.openroad/app_name/app_name.xml
.openroad/app_name/component.xml
```

This is useful for debugging and audit, but it is local generated state.

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

## Portable XML source companions (format 1)

Application exports now write this additional **tracked source** directory:

```text
app_name/.gorak-source/
├── format                   # 1
├── application.xml          # full application metadata
└── components/
    └── component.xml        # full XML for each exported component
```

Commit this directory. Unlike `.openroad`, it is independent of a database's
synchronization state and is required to restore source structures not yet fully
represented in readable files. A clean clone can use these companions to create
applications containing exported frames, globals, 3GL declarations, and other
preserved component types. Newly authored procedures/classes still need no XML.

Readable app metadata overrides its represented XML fields. Component scripts,
represented metadata, frame markup and existing field-default properties overlay
the preserved component XML. Unedited opaque content is retained. See
[component editing](component-editing.md) for supported shapes and acceptance.
Unsupported edits are rejected before import.

Do not edit companions independently of their readable files or rename component
folders/files without updating source identities. A companion without its readable
component is rejected; deletion reconciliation belongs to the sync-planning work.
The format marker is checked on restore. Unknown versions and unrecognized XML
root structures are rejected rather than partially imported.

Full and component exports refresh their corresponding companions. Pushes need
not rewrite them: reconstruction applies the current readable edits.
OpenROAD XML contents are preserved without inventing IDs; deployment baselines,
credentials, trace logs, and recovery files remain outside versioned source.

After upgrading an existing export-only project, export its applications once to
produce companions before attempting a cache-free clone restoration. Reconcile pending local edits before exporting. Ordinary `gorak sync` plans a
safe pull and refuses conflicts; direct export is not a conflict-resolution tool.

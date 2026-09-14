# Files and formats

## Versioned source and local state

```text
project/
├── gorak.json
├── app_name/
│   ├── app.json
│   ├── component.w4gl
│   └── frame_component.wml
└── .openroad/                 # ignored operational state
```

Commit application folders and `gorak.json`. Keep `.env` and `.openroad/` out of
Git. XML is an import/export transport and synchronization baseline under
`.openroad/`; it supplies no missing source information for format 2.
A fresh clone can reconstruct supported applications without XML, an old cache,
or the original database. Required external source/image dependencies must be
installed or included in the project.

## Complete readable source (format 2)

New exports mark `.w4gl` front matter with `source_format = 2`. The component table
contains named native metadata. The optional `===` body is the component script;
frame layout and event scripts are in the corresponding `.wml` file.

```toml
source_format = 2

[proc4glsource]
datatype = "integer"

===
PROCEDURE p4_score(capsules = integer) =
{
    RETURN capsules * 10;
}
```

Complex metadata uses named nested tables and ordered `row` arrays. For example,
class attributes contain `displayname`, `datatype`, `isnullable`, and any other
exported properties. Array containers retain `row_class` and other native metadata.
`_type` identifies an explicit native subtype; `_attributes` holds native element
attributes; `_text` preserves meaningful text on structured metadata. These are
parts of the source model, not a second copy of a component or its script.
Unknown properties/types and incompatible row types are refused.

Field-default palettes are represented once in each frame's
`[framesource.fielddefaults]` metadata. Format 2 does not inherit legacy
`field_defaults.json` files: layout values and palette metadata are explicit.
This preserves absent properties, duplicate style rows and container metadata
without guessing which default style was intended. Migration folds existing
repository/application/frame defaults into the complete frame metadata.

Optional `script_prefix` and `script_suffix` preserve native leading/trailing
whitespace only. Edit the script below `===`; it appears in exactly one place.
`component_attributes` holds any additional native component attributes.

## Frame markup

Format 2 WML has `<frame source_format="2">`. Properties appear as attributes,
structured properties as child elements, and native array wrappers retain their
metadata. Typed rows use their concrete field names:

```xml
<frame source_format="2">
  <topform width="6000" height="4000">
    <childfields row_class="formfield">
      <entryfield name="capsules" datatype="integer"
                  xleft="200" ytop="1000" width="1800" height="300"/>
      <buttonfield name="calculate" textlabel="Calculate score"
                   xleft="200" ytop="1500" width="1800" height="300">
        <script><![CDATA[on click = { score = p4_score(capsules = capsules); }]]></script>
      </buttonfield>
    </childfields>
  </topform>
</frame>
```

Keep identifiers and event scopes consistent. Explicitly supply the intended
properties when adding controls; no hidden palette supplies missing layout.
Native alignment such as `gravity` is preserved when present. See
[component editing](component-editing.md) for geometry verification.

## Application metadata

`app.json` uses `"source_format": 2`. It retains friendly scalar names such as
`starting_component`, `description`, and `database_name`. Structured
`included_applications` has an ordered `row` array with native `appname`,
`imgfilename`, `version`, and `sequence` properties, plus `row_class`.
The core include is explicit when exported. Other native application properties,
such as `commandline`, `taggedvalues`, and `appflags`, occur once in this metadata.
An absent property stays absent; an empty value remains explicitly empty.

## Migrating existing projects

```sh
gorak migrate-source
git diff
```

This local command reads the old companions or cached export, applies pending
readable edits and legacy field-default inheritance, then verifies exact
reconstruction from the proposed format-2 files before installing them. It removes
legacy `.gorak-source` files and consumed field-default JSON, preserving before-images
and the migration plan under `.openroad/migrations/`. It never changes the database,
its synchronization baseline, target binding, revision checkpoint or generation.
Locks, pending operations and quarantine must be resolved before migration.

Do not delete old XML before migrating: incomplete legacy projections cannot
recover information they never contained. Unknown legacy source shapes cause an
explicit refusal before source replacement. Keep the recovery evidence and extend
schema support for that shape. New exports never create `.gorak-source`.

The earlier compact procedure/class authoring syntax remains supported for new
components. Existing legacy exports should be migrated before ordinary sync;
reconstruction no longer consults XML companions or caches.

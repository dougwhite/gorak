# Image assets

Use an application-relative PNG reference in WML:

```xml
<bgbitmap src="images/background.png" path="art/background.png"/>
```

`src` locates the PNG; optional `path` preserves the original OpenROAD filename
and defaults to `src`. Import embeds the pixels; deployed applications do not
read that path. The PNG and reference are sufficient: no `.bitmap.json`, mask
file, or native XML cache is required.

Frame window icons accept `windowicon = {src = "images/icon.png", path = "art/icon.ico"}`
in `.w4gl`; application `window_icon` in `app.json` accepts the equivalent JSON
object. A plain path string remains sufficient for a newly authored icon.
Stylesheet bitmap objects and class-icon entries use the same reference fields.
Stylesheet paths are relative to the stylesheet directory.

Export derives dimensions, pixel storage and ordinary defaults from the PNG.
Nondefault native values remain as optional reference attributes. Preserve these
when editing source; [encoding notes](bitmap-encoding.md) describe their meaning
and limits. Resizing a masked image requires replacing or removing its `mask`
attribute. Changing an indexed/monochrome image's mode may require removing its
palette/padding attributes to treat it as a new image.

Export reuses assets with the same original path/name and matching content.
Collisions receive `-01`, `-02`, etc.; different original names stay independent.
Image edits affect every reference. Missing assets block synchronization;
unreferenced assets are not automatically removed. References must stay under
`images/`; symlinks are unsupported. Re-export earlier sidecar-based checkouts.

Class icons live in `<component>.icons.json`:

```json
{"version": 1, "key": "(icons/example)", "entries": [
  {"id": "1", "src": "images/icon.png", "path": "art/icon.ico"}
]}
```

The key must match the class's `class_icons` tagged value. Entry order and IDs are
preserved without assigning meanings to the slots.

Supported embedded layouts are monochrome, indexed, BGR and BGRA, including the
observed icon-mask format. Unknown layouts fail explicitly; unloaded bitmap
placeholders and existing inline source remain readable. PNG alpha bytes are
preserved, but OpenROAD's rendering may differ from PNG viewers. This does not
archive separately stored runtime database bitmaps or add general multi-image ICO
file import.

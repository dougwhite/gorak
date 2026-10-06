# Image assets

Use an application-relative PNG reference in WML:

```xml
<bgbitmap src="images/background.png"/>
```

Frame window icons use `windowicon = "images/icon.png"` in `.w4gl` metadata;
application icons use `"window_icon": "images/icon.png"` in `app.json`.
Stylesheet references are relative to their stylesheet directory; shared project
styles use the project’s `images/` directory. New PNGs need no sidecar. Import embeds their pixels in OpenROAD source; deployed
applications do not depend on the source directory.

Exported PNGs have an adjacent `<name>.png.bitmap.json` containing version `1`,
native header/footer fields, pixel mode, and any palette or padding details.
Optional masks are separate monochrome PNGs referenced by that metadata. Keep
these files together. Image edits affect every referencing component; missing
assets block synchronization. Changing an exported pixel mode or resizing a masked
image requires explicitly removing its native metadata to treat it as a new PNG.

Export reuses assets only when the original path/name signifier and bitmap content
match, including retained metadata. Collisions receive `-01`, `-02`, etc.; different
original signifiers stay independent. Unreferenced assets are not automatically
removed. References must stay under `images/`; symlinks are unsupported.

Class icons live in `<component>.icons.json`:

```json
{"version": 1, "key": "(icons/example)", "entries": [
  {"id": "1", "src": "images/icon.png"}
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

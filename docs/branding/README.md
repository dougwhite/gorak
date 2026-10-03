# gorak branding

The gorak mascot is a diligent little ork worker: code brackets in his ears,
a terminal prompt on his work bandana, and a friendly expression.
Always spell **gorak** in lowercase, including headings and UI labels.

## Assets

| Asset | Use |
| --- | --- |
| `gorak-logo.svg` | Horizontal logo for light backgrounds, documentation and README pages |
| `gorak-logo-dark.svg` | Horizontal logo with pale lettering and details for dark backgrounds |
| `gorak-icon.svg` | Square, transparent ork icon; master for normal-size exports |
| `gorak-icon-small.svg` | Same icon without the bandana highlight and eye glints, for 16–32 px |
| `gorak-icon-mono.svg` | Single-color icon; defaults to black and uses `currentColor` |
| `gorak-icon-{16,32,48,64,128,256,512}.png` | Transparent PNGs; use the 128 or 256 px version for extension/package icons |
| `favicon.ico` | Multi-resolution favicon containing 16, 32 and 48 px images |

![gorak icon](gorak-icon-128.png)

All SVGs contain editable vector artwork, with no embedded raster images,
external resources or font dependencies. The wordmark is outlined. Keep the
square icon canvas and its padding when exporting; preserve proportions.
The tiny icon deliberately retains the terminal prompt and bracket ears.
Use SVGs at arbitrary sizes, and PNGs where the consumer requires raster images.
For a monochrome SVG embedded as an HTML image, `currentColor` does not inherit
from the surrounding page: set its color inside the SVG or inline the SVG.

## Palette

| Color | Hex |
| --- | --- |
| Charcoal | `#26332e` |
| Ork green | `#86a34e` |
| Ivory details | `#fffdf5` |
| Pale details for dark backgrounds | `#e7eee9` |

## Exporting

Edit the SVG masters in a vector editor such as Inkscape. Re-export affected
PNGs when their master changes. For example, from the repository root:

```sh
inkscape docs/branding/gorak-icon.svg --export-width=128 --export-height=128 --export-filename=docs/branding/gorak-icon-128.png
inkscape docs/branding/gorak-icon-small.svg --export-width=32 --export-height=32 --export-filename=docs/branding/gorak-icon-32.png
```

The assets are shared branding for the gorak ecosystem. Adding them here does
not configure the separate VS Code extension or other applications to use them.

# Bitmap encoding observations

These defaults were measured across 6,385 exported assets and checked against
controlled native image fixtures. Correlation establishes reconstruction rules,
not undocumented OpenROAD attribute names. Positions below are zero-based within
the decoder's header/tail arrays, excluding pixel and mask buffers.

| Native data | Reconstruction |
| --- | --- |
| Header 0 | `12:bitmapobject` |
| Header 1–3 | `0, 1, 9`; all observed assets agree |
| Header 4 | Pixel buffer length |
| Header 5 | Length-prefixed `path`, defaulting to `src` |
| Header 6–9 | `0, 1, 2, 0`; all observed assets agree |
| Header 10–11 | PNG width and height |
| Header 12 | `2` for monochrome, `12` with a mask, otherwise `4`; `native-flags` overrides |
| Header 13 | Indexed PNG palette size; otherwise 0 for monochrome, 256 for RGB/RGBA; `palette-count` overrides |
| Tail 0–4 | All zero in the observed set |
| Tail 5 | Mask byte length, or `-1` without a mask |
| Tail 6 | Monochrome/indexed `0`, RGB `1`, RGBA `3`; `native-pixeltype` overrides |
| Tail 7–9 | Default zero |
| Tail 10–11 | Null strings (`-1:`); other values currently refused |

Header 12 is not bits per pixel: indexed, RGB and RGBA images all occur with
value 4. Every observed mask accompanies value 12, but 56 value-12 images have no
mask. Tail 6 follows PNG mode except for one indexed image carrying value 2.
Fifteen indexed images have tail 7 = 1 and a nonzero tail 8. These resemble a
colour-key enable/index pair, but the index cannot be derived from the first
pixel reliably. Their semantics remain unconfirmed; `native-t7` and `native-t8`
preserve them without assigning speculative names.

Nondefault constant slots use `native-h1`, `native-h2`, `native-h3`, `native-h6`
through `native-h9`, and `native-t0` through `native-t4`, `native-t7` through
`native-t9`. `native-h5="-1"` with `path=""` preserves a null filename rather
than an empty filename. There is no per-image version or redundant mode field.

Indexed PNGs retain palette RGB entries and pixel indices. Their native fourth
palette byte is not assumed to mean alpha: `palette-flags` retains nonzero bytes.
RGB/RGBA native palettes are normally all zero; `palette` preserves exceptions.
Monochrome pixels are inverted to/from the observed native representation;
`padding` retains nonzero unused row-end bits. None of these bytes can generally
be recovered from visible pixels.

`palette`, `palette-flags` and `padding` are base64-encoded zlib byte streams.
`mask` contains `WIDTHxHEIGHT:` followed by the same encoding of the exact native
mask bytes, including unused bits. Dimensions protect against accidental resize.
These attributes contain ancillary native data, never the main pixel buffer.
Missing attributes select the defaults above; invalid or oversized values fail.

Reference fields are identical in WML attributes, icon objects and stylesheet
objects. Rebuilding preserves decoded native fields and buffers; compression
runs and XML line wrapping may change. It does not establish that every
OpenROAD version renders PNG alpha identically to an image viewer.

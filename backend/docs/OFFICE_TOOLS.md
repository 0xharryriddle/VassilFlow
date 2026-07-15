# Office Document Tools

VassilFlow provides structured tools for inspecting and editing Office
documents without giving the agent a general-purpose shell command.

## Enable the tools

New configurations include the Office tools by default. Existing installations
can merge them according to their current file permissions:

```bash
make config-upgrade
make doctor
```

`office_inspect` belongs to `file:read`. `office_edit` and `office_render`
belong to `file:write`, so custom agents that omit the write group cannot
modify documents or create visual-QA artifacts.

Docker deployments start the isolated Office renderer automatically. For a
local backend, start only the renderer sidecar when visual QA is needed:

```bash
docker compose -p vassilflow-dev -f docker/docker-compose-dev.yaml up --build -d office-renderer-proxy
```

The local client uses `http://127.0.0.1:8003` by default. Set
`VASSILFLOW_OFFICE_RENDERER_URL` when the renderer is hosted elsewhere.

## PPTX native round-trip corpus

PPTX write-surface changes are gated by the native round-trip corpus under
`tests/fixtures/office/pptx/roundtrip`. Its deterministic VassilFlow seed
covers mixed runs, paragraph layout, direct shape style, text-box margins,
vertical anchoring, multiscript text, linear and radial gradients, connector
style, preset geometry, direct RGB pattern fill, and embedded PNG plus baseline
JPEG shape fills with stretch, crop, tile, and centered framing. It also covers
direct slide backgrounds using RGB solid, bounded linear gradient, stretched
JPEG, tiled PNG, and centered PNG fills. Slide 13 adds native `p:pic` objects
with shared PNG ownership, baseline JPEG ownership, crop, fill-rectangle,
compression, and direct effects metadata. Each required producer
must open and save that exact seed, emit a hash-bound receipt, preserve the
manifest's semantic contract, remain editable, and pass visual QA.

Create the deterministic seed from `backend/`:

```powershell
uv run python scripts/build_pptx_roundtrip_seed.py `
  --output tests/fixtures/office/pptx/roundtrip/seed-v1.pptx `
  --overwrite
```

Create a native fixture from the repository root on a Windows host with the
target application installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/office-pptx-native-roundtrip.ps1 `
  -Producer PowerPoint `
  -InputPath backend/tests/fixtures/office/pptx/roundtrip/seed-v1.pptx `
  -OutputPath backend/tests/fixtures/office/pptx/roundtrip/powerpoint-16-v1.pptx `
  -ReceiptPath backend/tests/fixtures/office/pptx/roundtrip/powerpoint-16-v1.receipt.json `
  -Overwrite
```

Use `-Producer WPS` with separate WPS fixture and receipt paths for that lane.
The harness requires the named native COM application and has no alternate
producer. If WPS owns the shared PowerPoint COM registration, the PowerPoint
lane starts an installed `POWERPNT.EXE` automation process directly and refuses
to attach while another PowerPoint process is open. No registry change is
required. Full update instructions live beside the corpus fixtures.

The v1 corpus has verified Microsoft PowerPoint 16 and WPS Presentation 12
lanes. Typed PPTX run, paragraph, shape, connector-line, direct slide
background, and source-only picture replacement is enabled only while that
readiness gate remains satisfied. Corpus tests exercise writes on every verified fixture,
including same-font metadata preservation, exact semantic readback,
touched-part isolation, native reopen, and rendered visual QA.

## Supported workflow

1. Upload or place a `.docx`, `.xlsx`, or `.pptx` file under `/mnt/user-data`.
2. Call `office_inspect`. For DOCX, read a bounded paragraph view and set
   `include_runs: true` before building run selectors. For XLSX, omit
   `sheet_name` to list worksheets, then inspect one bounded `cell_range` and
   set `include_cell_styles: true` before building style selectors. For PPTX,
   use `start_slide` and `max_slides` to inspect a bounded slide window. Set
   `include_pptx_formatting: true` for direct shape/text formatting, then use
   exact returned object paths in `pptx_selector` when a narrower read is
   needed. Set `include_pptx_annotations: true` for speaker notes and review
   comments, or `include_pptx_dynamics: true` for authored animation effects.
   Set `include_pptx_media_gc_plan: true` only when a package-wide,
   non-destructive image cleanup dry-run is needed; this analysis is independent
   of the selected slide window and object selector.
3. Call `office_edit` with format-specific typed operations. PPTX accepts
   paragraph-local literal replacement on exact authored-ID shape paths and
   direct formatting on exact shape, connector-line, run, paragraph, or slide
   paths returned by inspection. Embedded picture sources can be replaced on
   exact authored-ID picture paths using the returned name and source SHA-256
   as stale guards.
4. Write intermediate files to `/mnt/user-data/workspace` or final files to
   `/mnt/user-data/outputs`.
5. Call `office_render` with a new output directory.
6. If `has_more` is true, render the next page window and continue until the
   manifests cover every page in the current Office file.
7. When `visual_review_status` is `pending`, inspect every returned PNG with
   `view_image` in a separate model step. `present_files` rejects same-step or
   incomplete review and verifies each reviewed image against its manifest hash.
8. When `visual_review_status` is `external_review_required`, the active model
   cannot inspect the pages. Present the final Office document with that explicit
   warning and do not claim visual QA passed.
9. Call `present_files` for the final Office document, not the internal QA images.

Example edit operation:

```json
{
  "source_path": "/mnt/user-data/uploads/report.docx",
  "output_path": "/mnt/user-data/outputs/report-revised.docx",
  "operations": [
    {
      "type": "replace_text",
      "find": "Draft",
      "replace": "Final",
      "occurrence": "all",
      "require_match": true
    }
  ]
}
```

Example render request:

```json
{
  "path": "/mnt/user-data/outputs/report-revised.docx",
  "output_dir": "/mnt/user-data/workspace/report-visual-qa",
  "start_page": 1,
  "max_pages": 1,
  "dpi": 120
}
```

Example PPTX inspection, edit, and static visual-QA requests:

```json
{
  "path": "/mnt/user-data/uploads/deck.pptx",
  "start_slide": 1,
  "max_slides": 20,
  "include_pptx_formatting": true,
  "include_pptx_annotations": true,
  "include_pptx_dynamics": true,
  "include_pptx_media_gc_plan": true,
  "pptx_selector": {
    "paths": ["/slide[1]/shape[@id=7]"],
    "kinds": ["text_box"],
    "has_text": true
  }
}
```

```json
{
  "source_path": "/mnt/user-data/uploads/deck.pptx",
  "output_path": "/mnt/user-data/workspace/deck-revised.pptx",
  "operations": [
    {
      "type": "replace_pptx_text",
      "paths": ["/slide[1]/shape[@id=7]"],
      "find": "Draft",
      "replace": "Final",
      "occurrence": "all",
      "require_match": true
    }
  ]
}
```

```json
{
  "source_path": "/mnt/user-data/workspace/deck-revised.pptx",
  "output_path": "/mnt/user-data/workspace/deck-formatted.pptx",
  "operations": [
    {
      "type": "format_pptx_runs",
      "runs": {
        "targets": [
          {
            "path": "/slide[1]/shape[@id=7]/paragraph[1]/run[1]",
            "expected_text": "Final"
          }
        ]
      },
      "formatting": {
        "bold": true,
        "font_size": 24.5,
        "color": "#1F4E79",
        "font": "Aptos"
      }
    },
    {
      "type": "format_pptx_paragraphs",
      "paragraphs": {
        "targets": [
          {
            "path": "/slide[1]/shape[@id=7]/paragraph[1]",
            "expected_text": "Final"
          }
        ]
      },
      "formatting": {
        "alignment": "center",
        "space_after": 8,
        "line_spacing_percent": 120
      }
    },
    {
      "type": "format_pptx_shapes",
      "shapes": {
        "targets": [
          {
            "path": "/slide[1]/shape[@id=7]",
            "expected_name": "Summary card"
          }
        ]
      },
      "formatting": {
        "fill": {
          "type": "solid",
          "color": "#D9EAF7"
        },
        "line": {
          "fill": {
            "type": "solid",
            "color": "#1F4E79"
          },
          "width_points": 2.5,
          "cap": "square",
          "dash": "large_dash",
          "join": "miter",
          "miter_limit_percent": 800
        },
        "text_box": {
          "margin_left": 12,
          "margin_top": 8,
          "margin_right": 12,
          "margin_bottom": 8,
          "vertical_anchor": "middle"
        }
      }
    },
    {
      "type": "format_pptx_shapes",
      "shapes": {
        "targets": [
          {
            "path": "/slide[1]/shape[@id=7]",
            "expected_name": "Status panel"
          }
        ]
      },
      "formatting": {
        "fill": {
          "type": "gradient",
          "stops": [
            {
              "position_percent": 0,
              "color": "#203864"
            },
            {
              "position_percent": 42.5,
              "color": "#4472C4",
              "opacity_percent": 70
            },
            {
              "position_percent": 100,
              "color": "#70AD47"
            }
          ],
          "geometry": {
            "type": "linear",
            "angle_degrees": 125,
            "scaled": false
          },
          "rotate_with_shape": false
        }
      }
    },
    {
      "type": "format_pptx_shapes",
      "shapes": {
        "targets": [
          {
            "path": "/slide[3]/shape[@id=3]",
            "expected_name": "Radial focus"
          }
        ]
      },
      "formatting": {
        "geometry": {
          "type": "preset",
          "preset": "hexagon"
        },
        "fill": {
          "type": "gradient",
          "stops": [
            {
              "position_percent": 0,
              "color": "#FFF2CC"
            },
            {
              "position_percent": 45,
              "color": "#ED7D31",
              "opacity_percent": 80
            },
            {
              "position_percent": 100,
              "color": "#7F6000"
            }
          ],
          "geometry": {
            "type": "path",
            "path": "circle",
            "fill_to_rectangle": {
              "left_percent": 20,
              "top_percent": 40,
              "right_percent": 80,
              "bottom_percent": 60
            }
          },
          "rotate_with_shape": true
        }
      }
    },
    {
      "type": "format_pptx_shapes",
      "shapes": {
        "targets": [
          {
            "path": "/slide[4]/shape[@id=3]",
            "expected_name": "Pattern panel"
          }
        ]
      },
      "formatting": {
        "fill": {
          "type": "pattern",
          "preset": "weave",
          "foreground_color": "#C00000",
          "background_color": "#FFF2CC"
        }
      }
    },
    {
      "type": "format_pptx_lines",
      "lines": {
        "targets": [
          {
            "path": "/slide[2]/connector[@id=5]",
            "expected_name": "Flow connector"
          }
        ]
      },
      "formatting": {
        "compound": "triple",
        "alignment": "inset",
        "head_end": {
          "type": "stealth",
          "width": "large",
          "length": "small"
        },
        "tail_end": {
          "type": "oval",
          "width": "medium",
          "length": "large"
        }
      }
    },
    {
      "type": "format_pptx_shapes",
      "shapes": {
        "targets": [
          {
            "path": "/slide[5]/shape[@id=3]",
            "expected_name": "Image panel"
          }
        ]
      },
      "formatting": {
        "fill": {
          "type": "image",
          "image_path": "/mnt/user-data/uploads/panel.png",
          "rotate_with_shape": false,
          "crop": {
            "left_percent": 5,
            "top_percent": 10,
            "right_percent": 15,
            "bottom_percent": 20
          }
        }
      }
    },
    {
      "type": "format_pptx_slide_backgrounds",
      "slides": {
        "targets": [
          {
            "path": "/slide[6]",
            "expected_part_name": "ppt/slides/slide6.xml"
          }
        ]
      },
      "formatting": {
        "type": "image",
        "image_path": "/mnt/user-data/uploads/background.png",
        "mode": "tile",
        "tile": {
          "offset_x_emu": 0,
          "offset_y_emu": 0,
          "scale_x_percent": 50,
          "scale_y_percent": 50,
          "alignment": "top_left",
          "flip": "none"
        }
      }
    }
  ]
}
```

Source-only picture replacement uses the exact `source.sha256` returned on the
inspected picture object:

```json
{
  "source_path": "/mnt/user-data/workspace/deck-formatted.pptx",
  "output_path": "/mnt/user-data/workspace/deck-picture-replaced.pptx",
  "operations": [
    {
      "type": "replace_pptx_picture_sources",
      "pictures": {
        "targets": [
          {
            "path": "/slide[13]/picture[@id=3]",
            "expected_name": "Product image",
            "expected_source_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
          }
        ]
      },
      "image_path": "/mnt/user-data/uploads/product-replacement.jpg"
    }
  ]
}
```

`expected_text` always refers to the original inspected input for the whole
transaction. Re-inspect before editing when a target may have changed. Runs or
paragraphs whose inspection text is truncated beyond 4,000 characters are not
formatting targets. Shape and line formatting use the exact `name`, including
`null` or an empty value, returned by the same inspection as required
`expected_name`. Truncated names fail closed. Shape fill and line fill accept
direct RGB solid, no-fill, or bounded linear-gradient values; shape fill also
accepts a corpus-verified radial circle gradient, direct RGB pattern fill, or
embedded PNG or baseline JPEG image fill.
Pattern fill requires one bounded OOXML preset plus explicit foreground and
background colors; it is shape-only and cannot be applied to a line or
connector. Shape fills, slide-background fills, and picture-source replacement
require a read-only `.png`, `.jpg`, or `.jpeg` path
under `/mnt/user-data/uploads`, `/mnt/user-data/workspace`, or
`/mnt/user-data/outputs`. Shape fills require an explicit rotate-with-shape
choice and may use four-edge crop percentages in stretch mode. Image mode is
stretch by default. Tile mode requires signed X/Y offsets, independent X/Y
scales, one of nine alignments, and an explicit flip. Center mode is the native
100-percent tile anchored at center; it preserves asset scale and may repeat
when the asset is smaller than its fill bounds. Linked images, URLs, data URIs,
base64 payloads, alpha/effect writes, and fill-rectangle tuning are rejected.
Each image is limited to 10 MiB, 8192 pixels
per dimension, and 16 million pixels. PNG input must use non-interlaced standard
encoding. JPEG input must be an 8-bit, single-scan baseline grayscale or
three-component image; progressive, arithmetic-coded, CMYK/YCCK, EXIF-bearing,
and multi-scan input is rejected.
Image assets are limited to 20 MiB per transaction. Text-box inset and
line-width measurements are in points. Every gradient requires 2-32 strictly
increasing RGB stops and optional per-stop opacity. Shape gradients also
require an explicit rotate-with-shape choice. Linear geometry requires angle
and scaling. Radial geometry requires all four focus-rectangle edges at
0.001-percent precision, with opposing edges summing to 100 percent.

```json
{
  "path": "/mnt/user-data/workspace/deck-formatted.pptx",
  "output_dir": "/mnt/user-data/workspace/deck-visual-qa",
  "start_page": 1,
  "max_pages": 12,
  "dpi": 120
}
```

PPTX inspection follows declared presentation order rather than slide-part
filenames. It returns slide dimensions, authored name, resolved layout, title
and visible text, hidden and master-shape state, direct background, notes
presence, and bounded counts for shapes, pictures, tables, charts, groups,
connectors, and embedded objects. Text nested inside groups and table cells is
included. Each logical object also has a collision-free path, local z-order,
exact EMU geometry when authored, and the relationship IDs it owns. Structured
click and hover interactions retain their precise object or text-run owner,
tooltip, safe slide/show navigation target, or bounded allowlisted external
URL. Unsafe external targets and unknown actions remain inspectable with
explicit unsafe markers and still block rendering.
An embedded picture object also returns a bounded `source` record containing
the relationship ID, resolved package part, effective content type, byte size,
and SHA-256 digest. This source digest is available without enabling the larger
formatting view and is the required stale guard for picture replacement.
With `include_pptx_media_gc_plan: true`, inspection also performs a bounded,
package-wide dry-run over embedded image parts under `ppt/media`. Contract
version 2 scans every declared `application/xml`, `text/xml`, or `+xml` part
within the XML budgets and reports standard `r:id`, `r:embed`, or `r:link`
references whose ID is not declared by that same source part. Other attributes
in a relationship namespace are not interpreted as relationship references. It
also builds the complete internal relationship graph from the package root.
Standard image relationships with zero source-XML references are projected out
of a second graph pass, so each candidate shows whether its source and target
were root-reachable before the filter and whether the target remains reachable
afterward. Image parts with zero incoming relationships are included as
separate evidence. Root-unreachable image parts are returned in a bounded,
hash-bound evidence view with their incoming relationship states and source
owners; this view is diagnostic and never marks an island for deletion.
Package-root image relationships are implicit live edges and remain protected.

Missing sources, parseable content whose declared content type is not XML,
malformed XML, undeclared `r:id`/`r:embed`/`r:link` references, nonstandard
image relationship types, and exhausted scan limits produce explicit blockers and make
`analysis_complete` false. `analysis_complete` applies only to the declared
`liveness_basis`; direct part-URI references are not interpreted, non-XML or
untyped part contents are not scanned, and non-image relationship semantics are
conservatively assumed live. Every plan and candidate has `actionable: false`;
`destructive` and `deletion_supported` are also always false. The package hash
and candidate target, source-part, and relationship-part hashes bind the
evidence to exact bytes.
`estimated_reclaimable_uncompressed_bytes` is an evidence total, not an
authorization to delete. Images outside `ppt/media`, including package
thumbnails, are returned as bounded protected records and stay outside scope.
Authored transitions are returned as typed effect, extension schema,
direction, speed, duration, advance behavior, and markup-compatibility fallback
metadata. Supported `mc:Choice` branches are selected from their `Requires`
namespaces. With `include_pptx_dynamics: true`, bounded animation records expose
effect class, preset, duration, trigger, nearest-wrapper delay, easing, restart,
repeat state, paragraph/chart build, motion path, stable timing-node path, and
the resolved target object path. Authored chart fan-out sharing one `grpId` is
reported as one logical effect. This is authored timing inspection, not
simulation of slideshow playback.
With `include_pptx_annotations: true`, speaker notes use
`/slide[N]/notes`. Legacy comments prefer authored `(authorId, idx)` paths;
modern threads and replies prefer their escaped authored IDs. Positional paths
are marked unstable only when an authored identity is absent or duplicated.
Author identity, timestamps, position, resolved state, paragraph boundaries,
fields, breaks, and tabs are retained under explicit output, source-scan,
author-map, and character budgets. Notes run and paragraph formatting is
included when `include_pptx_formatting` is also true.
Optional formatting inspection returns direct shape geometry/fill/line style,
picture crop and fill framing, direct picture effects, text-box layout,
paragraph properties, and source-order run, field, line-break, and tab
segments. It preserves explicit false values and never summarizes a mixed
textbox from only its first run. Table-cell paragraph and segment paths extend
the owning table object's stable path.

Object relationship metadata returns at most 100 IDs per object, with each ID
bounded to 256 characters. Count and truncation fields distinguish complete
ownership metadata from capped output; resource and interaction IDs use the
same string bound while relationship resolution continues against the full
authored ID internally.

PPTX object selectors are conjunctive. `paths` are exact, case-sensitive paths
returned by inspection; wildcards, combinators, regular expressions, and raw
property predicates are rejected. Optional filters cover object kinds, visible
text, authored name, and alt-text state. A selector filters only the returned
`objects` array. Slide text, inventory, and resources remain full-slide context
so relationship ownership and visual context are not silently reclassified.
The bounded resource graph reports owner paths, relationship type and mode,
resolved package part, effective content type, byte size, and SHA-256 for image
parts. Explicit
`*_returned` and `*_truncated` fields distinguish complete output from capped
inspection. Static rendering includes hidden slides and reports a same-numbered
`source_slide` for every output page. PPTX text replacement is exact-path,
case-sensitive, literal, and paragraph-local. It preserves existing run
properties, applies non-overlapping matches from right to left, and refuses
positional paths or matches that cross hyperlinks, fields, or unsupported text
boundaries.

PPTX formatting selectors target existing direct `a:r` runs or `a:p`
paragraphs under authored-ID shapes, including authored-ID group ancestors.
Run formatting supports explicit bold/italic values, 0.5-point font sizes,
single/double/none underline and strike, direct RGB text color, a combined
Latin/East Asian font, or explicit Latin, East Asian, and complex-script font
slots. Existing font-slot metadata and compatible color transforms such as
alpha are preserved; inspection also returns ordered luminance, shade, tint,
saturation, and hue transforms under explicit caps. Complex gradient, picture,
pattern, and group fills are not replaced by the RGB operation. Paragraph
formatting supports alignment, 0.01-point spacing before/after, and either
point or percent line spacing. Shape formatting supports direct solid/no fill,
typed RGB linear or radial circle gradients, typed direct RGB pattern fill,
typed embedded PNG or baseline JPEG stretch/crop/tile/center fill, a bounded
preset geometry, direct line fill/width, flat/round/square caps, eleven preset
dash styles,
round/bevel/miter joins with an optional miter limit, signed text-box insets
from -4032 to 4032 points, and top/middle/bottom vertical anchoring. Writable
preset geometry values are `rect`, `roundRect`, `ellipse`, `triangle`,
`rtTriangle`, `diamond`, `parallelogram`, `trapezoid`, `pentagon`, `hexagon`,
`heptagon`, and `octagon`; custom geometry and authored adjustment guides fail
closed.
`format_pptx_slide_backgrounds` targets exact `/slide[N]` paths and requires
the inspected `part_name` as `expected_part_name`. It can remove the direct
background or replace it with an RGB solid, bounded RGB linear gradient, or
embedded PNG/baseline JPEG image using stretch, explicit tile, or centered
framing. Centered framing uses a 100-percent center-aligned tile and may repeat
when the asset is smaller than the slide. It changes only the selected slide
part and any planned image relationship/media additions. Theme-reference,
shade-to-title, path-gradient, authored effect, crop, master, and layout
background writes fail closed.
`replace_pptx_picture_sources` targets only native `p:pic` objects with exact
authored-ID paths. Every target requires the exact inspected object name and
lowercase source SHA-256. The operation changes only the picture's embedded
image relationship. Crop, stretch framing, DPI, compression state, direct
picture effects, transform, geometry, placeholder metadata, alt text,
interactions, z-order, and animation identity remain untouched. Pictures with
linked sources, companion SVG relationships, multiple source blips, mixed
Strict/Transitional namespaces, video/audio identity, or unsupported existing
image content types fail before mutation. Replacement is copy-on-write: a
matching package image is reused, otherwise a new media part and relationship
are added. The prior relationship and media part are intentionally retained;
the optional inspection dry-run can identify later cleanup candidates, but
relationship and media deletion remain deferred.
`format_pptx_lines` targets exact authored-ID shapes or connectors and adds
single/double/thick-thin/thin-thick/triple compound lines, center/inset pen
alignment, and head/tail line ends. Line-end types are none, triangle, stealth,
diamond, oval, or open arrow; width and length independently accept small,
medium, or large. Tables, fields, default/end-run properties, bullets, RTL,
non-circle path gradients, pattern or image line fills, image effects,
effects/3D, custom
or adjusted geometry, connector routing, raw XML, and effective
theme/master/layout formatting remain outside this write surface. Formatting
is capped at 1,000 targets per transaction.

Example typed formatting transaction:

```json
{
  "source_path": "/mnt/user-data/uploads/report.docx",
  "output_path": "/mnt/user-data/workspace/report-formatted.docx",
  "operations": [
    {
      "type": "format_runs",
      "paragraphs": {
        "paragraph_indices": [3],
        "contains_text": "Quarterly result"
      },
      "runs": {
        "run_indices": [1]
      },
      "formatting": {
        "bold": true,
        "color": "#C00000",
        "font_size": 16
      }
    },
    {
      "type": "format_paragraphs",
      "paragraphs": {
        "paragraph_indices": [3]
      },
      "formatting": {
        "alignment": "center"
      }
    }
  ]
}
```

Example XLSX inspection and formatting transaction:

```json
{
  "path": "/mnt/user-data/uploads/report.xlsx",
  "sheet_name": "Summary",
  "cell_range": "A1:F40",
  "include_cell_styles": true
}
```

```json
{
  "source_path": "/mnt/user-data/uploads/report.xlsx",
  "output_path": "/mnt/user-data/workspace/report-formatted.xlsx",
  "operations": [
    {
      "type": "format_cells",
      "cells": {
        "sheet_name": "Summary",
        "ranges": ["B2:F2"],
        "contains_text": "Revenue"
      },
      "formatting": {
        "bold": true,
        "font_color": "#FFFFFF",
        "fill_color": "#1F4E79",
        "horizontal_alignment": "center",
        "number_format": "#,##0.00"
      }
    }
  ]
}
```

Paragraph filters are conjunctive and support 1-based indices, literal text,
style ID, body/table-cell context, and direct alignment. Optional run filters
support 1-based indices within each paragraph, literal text, direct toggle
states, underline/highlight/color, per-script fonts and sizes, and vertical
alignment. An empty selector is rejected so a formatting call cannot target
the whole document accidentally. Paragraph inspection includes direct layout
readback. Run inspection returns at most 200 runs across the requested
paragraph window and marks truncated paragraphs explicitly.

Run formatting supports the core typography properties plus explicit ASCII,
High ANSI, East Asian, and complex-script font slots, complex-script size,
underline color, double strike, caps, and vertical alignment. Paragraph
formatting supports alignment, spacing before/after, left/right and first-line
or hanging indents, keep-with-next, keep-lines, and page-break-before. Numeric
paragraph measurements are points in 0.05-point increments. First-line and
hanging indents are mutually exclusive.

XLSX cell selectors require an exact worksheet and one or more A1 cells or
rectangular ranges. Overlapping ranges are deduplicated and the total selected
area is capped at 10,000 cells. Optional filters are conjunctive and cover raw
value, literal text, formula/blank state, value type, core font/fill properties,
horizontal alignment, and number format. The first formatting allowlist covers
font name/size, bold, italic, strike, underline, RGB font and solid-fill colors,
horizontal/vertical alignment, wrapping, shrink-to-fit, rotation, indentation,
and number formats.

Rendering defaults to one page per call. It reports `pending` when the active
model has `view_image` and the page images are available to the Gateway;
otherwise it reports `external_review_required`. Remote-sandbox artifacts are
mirrored atomically into the Gateway's thread workspace for review. A
successful conversion is not a visual-QA pass; the page images still need
inspection for clipping, overlap, broken tables, missing glyphs, font
substitution, and page-flow regressions.

An edit or render can be committed successfully in a remote sandbox even when
the cross-filesystem Gateway mirror is unavailable. Successful responses expose
`commit_status` and `gateway_mirror_status`; an unavailable mirror includes a
warning, and render review is forced to `external_review_required`. Treat the
sandbox path as authoritative in that case.

## Safety contract

- Uploaded files are read-only edit sources.
- Destinations are limited to the current thread's workspace and outputs.
- Source and destination must be distinct. The validated result is staged beside
  the destination and atomically replaces it, preserving the source and any
  existing destination if the final storage operation fails.
- Operations run as one transaction and serialize only after every required
  match succeeds.
- Formatting uses typed selectors and a direct-property allowlist. Run
  formatting includes per-script font control without replacing unrelated
  theme, hint, complex-script, or underline metadata.
- Setting a literal underline RGB removes a previous underline theme binding;
  changing only the underline style preserves existing color/theme metadata.
- New properties are placed relative to known WordprocessingML siblings without
  globally sorting existing foreign or markup-compatibility children. Standard
  properties are kept ahead of the Word 2010 run-extension tail.
- The resulting package is validated before it is written. Validation covers
  ZIP limits, required OPC controls, the effective main-document content type,
  the internal root relationship, every internal relationship target and
  authored relationship reference, the Word document root/body, and structural
  element/paragraph/run/text limits. External relationships, signatures,
  macros, and embedded or ActiveX payloads remain inspectable as risk labels
  but are blocked before DOCX edit or render.
- DOCX, XLSX, and PPTX edits enforce an OPC preservation policy after
  serialization: archive comments, relative entry order, stable ZIP metadata,
  and every payload outside the operation-specific part allowlist must remain
  unchanged. ZIP data-descriptor and Deflate tuning bits may change when the
  same entry is repacked to a seekable stream. For DOS-created entries, Unix
  permission bits synthesized in the otherwise-unused upper half of
  `external_attr` are also treated as a container detail; security flags and
  DOS attributes remain protected. If every allowed operation matches zero
  targets, the exact source package is returned without serialization.
- Package size, entry count, XML size, and compression expansion are bounded.
- XLSX formatting patches only worksheet style references and `xl/styles.xml`.
  Formula text, cached formula values, cell values, worksheet structure, and
  every unrelated package part are preserved. New fonts, fills, number formats,
  and cell formats are deduplicated and capped to prevent style explosion.
- The XLSX contract accepts macro-free workbooks only. Style edits are also
  refused for signed, externally linked, data-connected, pivot/slicer,
  embedded-object, ActiveX, or data-model workbooks. Inspection never loads
  cached external workbooks.
- Every declared XLSX sheet must resolve through the supported worksheet
  relationship type before declared-cell limits are counted. Textual values,
  formulas, cached values, number formats, hyperlinks, and optional style
  strings are individually bounded and share a 200,000-character inspection
  budget with explicit truncation fields.
- XLSX rendering rejects signatures, macros, external links, data connections,
  embedded objects, and ActiveX before LibreOffice conversion. Inert
  pivot/slicer workbooks may still be inspected and rendered in the isolated,
  no-egress sidecar, but remain outside the edit contract.
- PPTX inspection accepts only a macro-free presentation main part and validates
  declared slide order, slide content types, every internal target in the
  package relationship graph, broken relationship references, XML bounds,
  object counts, and visible-text limits. Object paths prefer unique authored
  drawing IDs and use deterministic positional segments when IDs are missing or
  duplicated. Group descendants keep parent paths and local z-order. Resource
  traversal follows dependencies owned by the selected slide or object and
  excludes master-to-layout catalog back-references.
- The optional PPTX media cleanup dry-run scans at most 20,000 relationships,
  20 MiB per XML source part, and 50 MiB of source XML in total. Candidate and
  blocker arrays have independent output caps and explicit truncation fields.
  It validates relationship attributes across every declared XML part, builds
  root reachability before and after proven zero-reference image edges are
  filtered, blocks opaque or nonstandard ownership, excludes external images
  and image parts outside `ppt/media` from deletion scope, emits evidence-only
  records with exact byte hashes, and never mutates package bytes.
- PPTX text editing targets at most 100 exact authored-ID shape paths per
  operation and 10,000 literal replacements per transaction. Typed formatting
  targets at most 200 exact runs, 100 exact paragraphs, 100 exact authored-ID
  shapes, 100 exact authored-ID shape/connector lines, 50 exact slides, or 100
  exact authored-ID pictures per operation and 1,000 total targets per
  transaction. Every formatting target carries original inspected text,
  object name, slide part name, or picture source SHA-256 as its stale-path
  guard, and all guards are checked before the first mutation.
- A canonical XML-tree comparison permits only selected DrawingML text content,
  whitespace preservation, and requested direct formatting slots to change.
  Font metadata, color transforms, hyperlinks, fields, breaks, tabs, bullets,
  and unrelated shape/run/paragraph properties remain protected. Shape writes
  are limited to direct solid/no fill, direct line fill/width/cap/preset-dash/
  join, text-box insets, and top/middle/bottom anchoring. Direct line writes may
  additionally change typed compound/alignment and head/tail line-end slots on
  authored shapes or connectors. Picture replacement additionally masks only
  the selected `a:blip/@r:embed` source slot in the preservation check. Only
  touched slide parts are serialized; an exact no-op returns source bytes.
  Signatures, macros, linked external resources, unsafe actions, OLE/embedded
  packages, and ActiveX block editing, while allowlisted authored external
  hyperlinks are preserved.
- Optional PPTX formatting output has independent limits for table cells,
  paragraphs, text segments, duplicated text characters, and gradient stops.
  Counts and `*_truncated` fields make partial output explicit.
- PPTX interactions are bounded to 100 records per returned object and 2,000
  records per inspection window. Slide/window counts distinguish all authored
  interactions, selector matches, returned records, and truncation. Tooltips,
  actions, relationship IDs, and targets have independent string bounds.
- PPTX annotations are opt-in and bounded to 1,000 returned comment records,
  20,000 scanned comments/replies, 5,000 authors, 200,000 text characters per
  inspection window, 20,000 characters per notes body, and 4,000 per comment.
  Authored animations are opt-in and bounded to 5,000 scanned targets per slide
  and 2,000 returned records per window. Count, count-truncation, identity,
  resolution, and output-truncation fields remain explicit.
- PPTX rendering preserves allowlisted authored external hyperlinks but rejects
  linked external resources, local-file or executable hyperlink schemes,
  unsafe slide actions, signatures, macros, OLE/embedded packages, and ActiveX
  before LibreOffice conversion. The no-egress renderer does not dereference
  accepted hyperlinks.
  It is a static render: animations, transitions, morph effects, video,
  SmartArt, and 3D behavior still require review in the target presentation
  viewer.
- Custom XLSX number formats must have balanced quoted literals and bracket
  expressions, contain at most four semicolon-separated sections, and stay
  within Excel's 255-character limit.
- A replacement that crosses a hyperlink boundary is rejected.
- Ruby base text is inspectable once, while ruby annotations are protected from
  both replacement and typed run formatting.
- Existing destinations are not overwritten unless explicitly requested.
- Rendering runs in a sidecar without project mounts, credentials, or outbound
  network access. A fixed-route proxy connects the Gateway to the private
  renderer network without giving renderer code a route back to the Gateway.
- Render requests are limited to 12 pages, 96-200 DPI, and bounded response
  sizes. PDF rasterization runs in a killable worker process with a hard
  deadline. The Gateway verifies the exact requested page window, archive
  paths, PNG dimensions, and page digests. PPTX conversion exports hidden
  slides, requires PDF page count to equal declared slide count, and verifies
  each page's `source_slide` identity.
- A render output directory must be new or empty. Its completion manifest is
  written only after every requested page image succeeds. The manifest binds
  the pages to the source SHA-256 and versioned renderer pipeline fingerprint,
  including conversion-filter options and hashes of the installed font
  binaries. If a write fails before the manifest, discard that directory and
  retry with a new one.

## Current scope

The current implementation supports literal replacement and typed formatting
in main-body DOCX text, including paragraphs inside table cells. XLSX supports
bounded workbook/sheet/range inspection and direct cell formatting over
existing declared cells. PPTX supports bounded, relationship-aware inspection
with exact typed object selection, structured read-only interactions, optional
direct shape/text/picture formatting inspection, speaker notes, legacy and
threaded comments, authored transitions and animation effects, static
rendering, exact-path literal replacement in authored-ID shapes, and narrow
typed direct formatting for existing shapes, connector lines, runs,
paragraphs, and slide backgrounds. Existing native pictures support typed,
source-only PNG/baseline-JPEG replacement with name and digest guards. PPTX
inspection can also return bounded, fail-closed, read-only cleanup evidence for
embedded image relationships with zero source-XML references and `ppt/media`
image parts with zero incoming relationships, including package-wide XML
relationship integrity and package-root reachability before and after the
zero-reference filter. Root-unreachable image islands are exposed as bounded,
hash-bound protected evidence with incoming owner state. Those records are
never actionable. All three formats render through LibreOffice and PDFium.
Rendering reflects LibreOffice layout and may differ from Microsoft Office for
fonts, fields, formulas, print settings, or application-specific behavior.

DOCX headers, footers, notes, comments, fields, tracked changes, and text boxes
remain outside the edit contract. XLSX value/formula writes, formula
evaluation, cell creation, rich-text mutation, borders, conditional-format
mutation, charts, pivots, slicers, macros, and external links are deferred.
Regex/CSS-like selector grammars, theme mutation, raw XML mutation, and all
broader PPTX writes remain outside the current contract. Slide
creation/reordering, custom or adjusted geometry, z-order or connector-routing
changes, non-circle path gradients, pattern or image line fills,
custom-dash, effect/3D changes, picture creation/removal/crop/framing/effect
mutation, inherited/theme/master/layout backgrounds, text
creation/reconstruction, table or table-cell picture replacement, charts,
media-object creation or deletion/garbage-collection writes, notes,
comments, fields, breaks, tabs, bullets, and positional-path
targets are not mutated. PPTX formatting inspection and writes are direct-only:
theme, slide-master, layout, placeholder, list-style, table-style, inherited
effects, and WordArt inheritance are not resolved.
Animation event graphs, media timelines, slideshow playback, and effective
theme/master/layout formatting remain deferred even when authored metadata is
inspectable.

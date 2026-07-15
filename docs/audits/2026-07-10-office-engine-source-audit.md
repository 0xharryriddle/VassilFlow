# VassilFlow Office Engine Source Audit

Date: 2026-07-10
Last updated: 2026-07-15

## Scope

This audit records the source-informed design work for the VassilFlow Office
Engine. OfficeCLI is used as a technical reference; the product contract,
tool policy, paths, output schema, and runtime integration are owned by
VassilFlow.

Reference source:

- Repository: https://github.com/iOfficeAI/OfficeCLI
- Audited checkout: `b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`
- Current upstream compared: `4ba79f0b984e141f57f58d4398ba2df29e8187e8`
- License: Apache-2.0

The audited PPTX handler tree is byte-identical between those two commits.

## Source Read

- `src/officecli/Handlers/Word/WordHandler.Helpers.FindReplace.cs`
- `src/officecli/Handlers/Word/WordHandler.View.cs`
- `src/officecli/Handlers/Word/WordHandler.Set.cs`
- `src/officecli/Handlers/WordHandler.cs`
- `src/officecli/McpServer.cs`
- `src/officecli/DocumentLimits.cs`
- `src/officecli/officecli.csproj`
- `src/officecli/CommandBuilder.View.cs`
- `src/officecli/Core/WordPdfBackend.cs`
- `src/officecli/Handlers/Rendering/BasicRenderers.cs`
- `src/officecli/Handlers/Rendering/HandlerRenderInput.cs`
- `src/officecli/Handlers/Word/WordHandler.HtmlPreview.cs`
- `src/officecli/Handlers/Word/WordHandler.Selector.cs`
- `src/officecli/Handlers/Word/WordHandler.Helpers.RunFormat.cs`
- `src/officecli/Handlers/ExcelHandler.cs`
- `src/officecli/Handlers/Excel/ExcelHandler.Query.cs`
- `src/officecli/Handlers/Excel/ExcelHandler.Selector.cs`
- `src/officecli/Handlers/Excel/ExcelHandler.Set.Cells.cs`
- `src/officecli/Handlers/Excel/ExcelHandler.Helpers.Cell.cs`
- `src/officecli/Handlers/Excel/ExcelHandler.Helpers.Node.cs`
- `src/officecli/Core/ExcelStyleManager.cs`
- `src/officecli/Core/WorksheetBloatFilter.cs`
- `src/officecli/Handlers/PowerPointHandler.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.View.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Query.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Helpers.FindReplace.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Set.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Set.Shape.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.ShapeProperties.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Fill.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Effects.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Background.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Hyperlinks.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.NodeBuilder.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Resolve.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.HtmlPreview.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Notes.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Comments.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.ModernComments.cs`
- `src/officecli/Handlers/Pptx/PowerPointHandler.Animations.cs`
- `src/officecli/Handlers/Pptx/PptxBatchEmitter.Notes.cs`
- `src/officecli/Handlers/Pptx/PptxBatchEmitter.AuxParts.cs`
- `src/officecli/Core/PowerPointPngBackend.cs`
- `skills/officecli-pptx/SKILL.md`

## Classification

| Area | Classification | VassilFlow decision |
| --- | --- | --- |
| Machine-readable document inspection | Port | Bounded JSON paragraph view |
| Run-aware literal replacement | Port | Structured transaction, no shell command |
| Reverse-order match application | Port | Preserves offsets during multi-match edits |
| Hyperlink-boundary guard | Port | Reject edits that would damage link structure |
| Batch save-once behavior | Port | Apply in memory, validate, then write once |
| Exact no-op package preservation | Port | An allowed zero-match transaction returns the original DOCX/XLSX bytes without serialization |
| ZIP/XML resource limits | Port | Package, entry, expansion, and XML limits |
| DOCX relationship graph and active-content policy | Port | Resolve every internal target and authored relationship reference; inspect inert metadata, but block risky edit/render paths |
| DOCX structural XML preflight | Port | Bound element, paragraph, run, and text counts before materializing `document.xml` |
| Generic MCP command tool | Not suitable | Separate read/write tools under existing groups |
| Installer and automatic updater | Not suitable | No runtime downloads or self-update |
| Raw XML mutation | Defer | Too broad for the default agent capability |
| Regex, tracked changes, headers/footers | Defer | Requires broader fidelity corpus |
| Resident mode, plugins, watch server | Defer | No direct runtime need in the first batch |
| Renderer capability boundary | Port | Separate renderer client and isolated service |
| Page-filtered PNG output | Port | Bounded consecutive page windows with per-page artifacts |
| Native Microsoft Word renderer | Not suitable | Windows/Office-specific and unavailable in standard deployments |
| Full DOCX-to-HTML preview engine | Defer | Large parallel document model with high maintenance and fidelity risk |
| Screenshot success as visual-QA success | Not suitable | Rendering remains pending until every page is inspected |
| Typed paragraph/run selectors | Port | Conjunctive Pydantic selectors over inspected indices and direct properties |
| Core run and paragraph formatting | Port | Small OOXML allowlist with deterministic schema ordering |
| Per-script run font slots and complex-script size | Port | Explicit typed fields that preserve unrelated theme/hint metadata |
| Underline color, caps, double strike, vertical alignment | Port | Bounded direct-formatting fields with inspection readback |
| Paragraph spacing, indents, and pagination toggles | Port | Point-based typed fields with OOXML sibling preservation |
| Generic CSS-like selector language | Defer | Start with typed paragraph/run selectors after render baselines exist |
| Theme fonts/colors, effects, borders, shading, and raw property fallback | Defer | Requires a larger interoperability corpus and stricter schema validation |
| Bounded workbook/sheet/range inspection | Port | Typed XLSX metadata, values, formulas, cached values, and direct styles |
| XLSX declared-sheet relationship contract | Port | Every workbook sheet must resolve through a supported worksheet relationship before cell limits are counted |
| XLSX inspect character budget | Port | Bound each textual cell field and the shared response character total with explicit truncation markers |
| Cell selector grammar | Port selectively | Exact worksheet plus bounded typed A1 ranges and conjunctive filters |
| Base-style merge and style deduplication | Port | Controlled `styles.xml` records with a style-growth cap |
| XLSX LibreOffice rendering | Port | Existing isolated PDFium pipeline with the Calc PDF export filter |
| Full workbook save through a general Python workbook writer | Not suitable | Can clear formula caches and remove unsupported extension markup |
| Generic string/CSS selector parser and unbounded range materialization | Not suitable | Conflicts with typed tools and bounded resource policy |
| Raw workbook XML mutation, resident mode, and source metadata stamping | Not suitable | Conflicts with immutable sources and the VassilFlow tool boundary |
| Formula evaluation and formula writes | Defer | Cache validity and dependency recalculation need a separate contract |
| Macros, external links, pivots, slicers, charts, and embedded objects | Defer | Inspect/render only until mutation fidelity has dedicated corpora |
| Cell values, new blank cells, rich text, borders, and conditional formatting | Defer | Keep the first write surface style-only and existing-cell-only |
| Slide order through `p:sldIdLst` relationships | Port | Never infer presentation order from slide filenames |
| Group-descendant shape text and table-cell text | Port | Bounded visible-text inspection with flattened shape paths |
| PPTX object inventory | Port selectively | Shapes, text boxes, pictures/alt text, tables, charts, groups, connectors, OLE, and notes presence |
| PPTX object identity and resource ownership | Port | Stable nested paths, local z-order, exact authored geometry, relationship owners, content types, and bounded byte sizes are implemented read-only |
| Exact typed PPTX object selector | Port selectively | Conjunctive exact paths, object kinds, authored name/alt-text state, and case-sensitive visible text; no selector grammar |
| Direct PPTX shape and text formatting | Port selectively | Structured read-only fill, line, geometry, text-box, paragraph, and text-segment properties with explicit output caps |
| Ordered PPTX color transforms | Port selectively | Surface bounded luminance, shade, tint, saturation, and hue transforms in authored order while retaining direct alpha readback |
| Direct slide metadata and background | Port selectively | Authored slide name, resolved layout identity, master-shape state, and direct solid/gradient/image/theme-reference background are implemented read-only without resolving inheritance |
| Structured PPTX interactions | Port selectively | Preserve every object/run click or hover owner, tooltip, external hyperlink, internal slide target, and allowlisted show/media action under explicit caps |
| Direct picture framing and effects | Port selectively | Typed read-only crop, stretch/tile framing, compression state, alpha/luminance/grayscale/bilevel/duotone metadata; no raw effect XML |
| Speaker notes and review comments | Port selectively | Add bounded, opt-in notes plus legacy and modern threaded comment inspection while retaining relationship and author provenance |
| Authored slide transitions | Port selectively | Resolve supported markup-compatibility `Requires` branches, then expose typed effect, direction, timing, fallback, and truncation metadata without raw XML |
| Authored animation timing | Port selectively | Deduplicate authored `grpId` fan-out and expose stable timing-node paths, easing, restart, build, effect, and motion summaries |
| PPTX package preservation harness | Port | Snapshot OPC part payloads and ZIP metadata so future edits can prove that only allowlisted parts changed |
| Native PPTX producer round-trip corpus | Port | Gate write-surface growth on hash-bound Microsoft PowerPoint and WPS fixtures, semantic readback, editability, native reopen, and visual QA |
| Exact-path PPTX literal text replacement | Port selectively | Open the first PPTX write surface only for stable authored shape paths, paragraph-local literal matches, and run-preserving replacement |
| Reverse-order PPTX match application | Port | Apply non-overlapping matches from right to left so earlier offsets remain stable |
| PPTX typed subtree invariant | Port | Normalize only selected text or requested direct-formatting slots before canonical comparison; protect all unrelated DrawingML structure |
| PPTX regex or presentation-wide find/replace | Not suitable | Keep writes deterministic and explicitly scoped; no regex engine, root sweep, fuzzy selector, or implicit notes traversal |
| Destructive whole-shape text rebuild | Defer | Rebuilding paragraphs from one formatting sample can erase mixed runs, fields, breaks, tabs, hyperlinks, and language metadata |
| PPTX notes, table-cell, and comment writes | Defer | Each requires its own typed identity, relationship, preservation, and render corpus |
| Typed PPTX run and paragraph formatting | Port selectively | Exact authored-ID object paths plus original-text guards, bounded direct run/paragraph allowlists, metadata-preserving mutation, and native producer QA are implemented |
| Typed direct PPTX shape formatting | Port selectively | Exact authored-ID shape paths plus expected-name guards; bounded solid/no, RGB gradient/pattern, and embedded PNG stretch/crop fill, line fill/width/cap/preset-dash/join, text-box margins, and vertical anchoring are implemented |
| Notes body extraction from only placeholder index 1 | Not suitable | Resolve the authored body placeholder by type first, retain paragraph/run boundaries, and include fields, breaks, and tabs |
| Raw transition/timing XML passthrough and dump replay | Not suitable | Conflicts with typed inspection, bounded output, and preservation-first writes |
| Generic PPTX add/set/remove command surface | Not suitable | Keep format-specific typed operations behind the VassilFlow transaction boundary |
| Effective PPTX formatting cascade | Defer | Theme, master, layout, list-style, and placeholder inheritance require a separate fidelity contract |
| PPTX OPC and relationship validation | Port | Macro-free main part, declared slide types, every internal relationship target, broken-reference checks, and resource limits |
| Safe external PPTX hyperlinks | Port selectively | Preserve allowlisted authored links; continue blocking linked resources, local-file links, and executable URI schemes |
| PPTX action URI validation | Port selectively | Preserve slide jumps, show jumps, and embedded-media actions; block unknown or executable actions before conversion |
| Hidden-slide render identity | Port | Export hidden slides and bind each PDF page to its declared source slide |
| PPTX LibreOffice rendering | Port | Existing isolated PDFium pipeline with an explicit Impress PDF export contract |
| Native PowerPoint COM rendering | Not suitable | Windows/Office-specific and unavailable in standard deployments |
| Full PPTX HTML/SVG renderer | Defer | Large parallel layout engine with native-feature fidelity risk |
| Generic PPTX selectors, raw XML, and mutation | Not suitable | Conflicts with the typed, capability-scoped VassilFlow tool boundary |
| PPTX slide creation/reordering and table/chart/media-object writes | Defer | Keep broader writes closed until dedicated source/edit/render corpora pass; embedded PNG shape fill is separately bounded and verified |
| Full animation trigger graphs and media timelines | Defer | Typed authored-effect inventory comes first; trigger ordering, event dependencies, and playback behavior still require viewer-level fixtures |
| Effective theme/master/layout formatting | Defer | Direct formatting remains authoritative until placeholder and style inheritance can be verified across viewers |
| SmartArt and 3D semantics | Defer | Static resource inspection/render only; verify dynamic behavior in a presentation viewer |

## Implemented Contract

- `office_inspect` belongs to `file:read`.
- `office_edit` belongs to `file:write`.
- Source files may be read from uploads, workspace, or outputs.
- Uploads are immutable; edited files may be written only to workspace or outputs.
- An edit is transactional: every required operation must match, the resulting
  package must validate, and only then are bytes written.
- DOCX and macro-free `.xlsx` are enabled for inspection, editing, and
  rendering. Macro-free `.pptx` supports exact-path paragraph-local literal
  replacement plus bounded direct formatting on existing runs and paragraphs
  under stable authored-ID shapes.
- `office_render` belongs to `file:write` because it creates QA artifacts.
- Rendering runs in a dedicated container without project mounts, credentials,
  or outbound network access in the bundled Docker topology.
- The renderer converts DOCX to PDF with LibreOffice and rasterizes bounded page
  windows with PDFium. The Gateway validates the returned archive, PNG headers,
  dimensions, and SHA-256 digests before writing pages.
- The renderer sits alone on a private internal network. A fixed-route proxy
  bridges only the health, DOCX render, XLSX render, and PPTX render endpoints to the
  Gateway network, so renderer code has no direct route back to the Gateway.
- The render manifest is a completion marker and records
  `visual_review_status: pending`; it never claims that conversion alone passed
  visual QA.
- Render manifests bind outputs to the source SHA-256 and a versioned pipeline
  fingerprint covering LibreOffice, PDFium, conversion-filter options, and
  hashes of the installed font binaries. The client requires the exact
  requested page window.
- PDFium rasterization runs in a child process with a hard deadline so native
  rendering work can be terminated rather than merely abandoning a thread.
- `office_inspect(include_runs=true)` exposes bounded run paths and direct
  formatting for selector construction.
- Formatting operations use typed paragraph/run selectors. Empty selectors are
  invalid, all filters are conjunctive, and edits remain transactional.
- Inspection exposes direct paragraph layout and expanded run metadata,
  including per-script font slots, underline color, complex-script size, caps,
  double strike, and vertical alignment.
- The formatting allowlist covers core run typography, explicit per-script
  fonts, underline color, complex-script size, caps, double strike, vertical
  alignment, and bounded paragraph layout/pagination properties. New
  properties require explicit OOXML ordering and render tests.
- Existing run-font theme attributes, font hints, complex-script values, and
  underline color/theme attributes survive unrelated formatting updates.
- Underline style updates preserve existing color/theme metadata, while an
  explicit RGB underline-color update removes the prior theme binding.
- Property insertion is minimal: known OOXML siblings guide placement of the
  new property, but existing foreign and `mc:AlternateContent` children are not
  globally reordered. Standard run properties are explicitly hoisted before a
  trailing Word 2010 extension block.
- DOCX package validation resolves the main document content type through a
  valid part override or extension default and verifies the internal root
  office-document relationship before parsing `word/document.xml`.
- DOCX validation also resolves every internal package relationship, rejects
  dangling `r:id`/`r:embed`/`r:link` references, and preflights element,
  paragraph, run, and text counts before materializing the main XML tree.
  External relationships, signatures, macros, and embedded or ActiveX payloads
  remain inspectable as risk labels but are refused for edit and render.
- Validated output bytes are staged beside the destination and replaced with a
  storage-level atomic operation. Remote sandbox outputs and render pages are
  mirrored atomically to the Gateway thread workspace when local review needs
  them.
- Ruby guide text is excluded from visible paragraph/run indices. Ruby base
  text remains inspectable, but the complete ruby structure is protected from
  replacement and run formatting.
- A remote sandbox commit and its Gateway mirror are reported as separate
  outcomes. Mirror failure leaves `commit_status: committed`, reports
  `gateway_mirror_status: unavailable`, emits a warning, and forces render
  review to an external client rather than returning a false transaction
  failure after the authoritative sandbox write.
- XLSX package preflight validates ZIP/OPC bounds, the macro-free workbook
  content type, the internal root workbook relationship, worksheet cell-count
  limits, and parser readability. Inspection lists workbook sheets first, then
  exposes at most 5,000 cells from an explicit or default bounded range.
- XLSX inspection separates raw values, formulas, cached formula values, value
  types, number formats, hyperlinks, merged ranges, and optional direct style
  metadata. Cached values are reported as stored data, never as a fresh
  calculation.
- XLSX formatting uses an exact worksheet plus one or more typed A1 ranges.
  Range filters are conjunctive, overlapping coordinates are deduplicated, and
  no operation may address more than 10,000 cells.
- Worksheet parts are resolved through workbook relationships before cell
  limits are applied. Significant whitespace in worksheet names is preserved,
  so selectors cannot silently resolve a neighboring sheet.
- Every declared workbook sheet must use the supported worksheet relationship
  contract; unknown sheet relationship types cannot bypass declared-cell
  limits. Textual cell values, formulas, caches, number formats, hyperlinks,
  and optional style strings share a response character budget and expose
  per-field plus response-level truncation markers.
- The XLSX writer does not round-trip the workbook through `openpyxl`. It uses
  `openpyxl` only for bounded parsing and selector matching, then patches cell
  style indices and `xl/styles.xml` with `lxml`. Formula `<f>`/`<v>` pairs,
  worksheet content, and every unrelated package part remain unchanged.
- Font, fill, number-format, and cell-XF records merge from the existing style,
  deduplicate against current records, and have a 500-record growth cap.
- Custom number-format writes and validation reject unbalanced quoted literals,
  unbalanced bracket expressions, more than four format sections, and codes
  longer than 255 characters.
- Editing refuses signatures, macros, external workbook links, data
  connections, pivots, slicers, embedded/ActiveX objects, and workbook data
  models. Inspection and isolated no-egress rendering remain available.
- The renderer accepts `.xlsx` through a fixed proxy route, converts with the
  LibreOffice Calc PDF filter, and uses the same bounded archive, hash,
  fingerprint, and pending-visual-review contract as DOCX.
- Rendering refuses signatures, macros, external workbook links, data
  connections, embedded objects, and ActiveX before LibreOffice starts.
  Macro detection includes VBA projects, macro-enabled content types, and
  Excel 4.0 international and non-international macro-sheet relationships.
  Inspection disables cached external-link loading; inert pivot/slicer files
  remain renderable in the isolated no-egress sidecar but are not editable.
- PPTX inspection resolves slides in declared presentation order, validates
  every internal target in the package relationship graph plus every selected
  slide relationship reference, and reports bounded
  visible text from nested group shapes and table cells. It also reports slide
  dimensions, hidden state, notes presence, object counts, picture alt-text
  gaps, and active-content risk labels.
- Optional PPTX formatting inspection reports structured direct shape geometry,
  fill and line styles, text-box layout, paragraph properties, and source-order
  run/field/break/tab segments. Paragraph, segment, table-cell, and duplicated
  text output are capped independently and expose truncation markers.
- Slide inspection reports authored slide names, resolved layout identity,
  master-shape visibility with authored/default provenance, and direct-only
  backgrounds.
  Object interactions retain click/hover trigger, precise object or text-run
  owner paths, tooltip, relationship/action provenance, and normalized slide or
  show-navigation targets. Picture formatting adds typed crop, stretch/tile,
  compression, and direct blip-effect metadata.
- Slide transitions are parsed from direct or markup-compatibility branches
  after evaluating each `mc:Choice` namespace requirement, then returned as
  typed effect, schema, direction, timing, advance, and fallback metadata.
  Optional dynamics inspection resolves authored animation effects and motion
  paths back to stable object paths. Timing-node IDs stabilize animation paths;
  chart fan-out is deduplicated by authored group ID, while easing, restart,
  paragraph/chart build, unresolved targets, and truncation remain explicit.
- Optional annotation inspection resolves speaker notes, legacy comments, and
  modern threaded comments through package relationships. Notes retain
  paragraph/run/field/break/tab structure; comments retain author, timestamp,
  position, thread, reply, and resolved-state provenance under shared output,
  source-scan, author-map, and character budgets. Legacy `(authorId, idx)` and
  modern thread/reply IDs stabilize paths when those authored identities are
  present.
- The typed PPTX object selector exact-matches stable object paths and can add
  conjunctive kind, authored name, alt-text state, and case-sensitive visible
  text filters. It filters only the returned object array; slide text,
  inventory, and resources remain full-slide inspection context.
- PPTX rendering uses the LibreOffice Impress PDF filter with hidden-slide
  export enabled and the same isolated, hash-bound, exact-window PDFium
  pipeline as DOCX/XLSX. Every rendered page records the same-numbered
  `source_slide`, and conversion fails if the PDF page count differs from the
  declared slide count. Rendering preserves allowlisted authored external
  hyperlinks, but refuses signatures, macros, linked external resources,
  local-file or executable hyperlink schemes, unsafe slide actions,
  OLE/embedded packages, and ActiveX before LibreOffice starts.
- `replace_pptx_text` accepts at most 100 exact authored-ID shape paths, applies
  non-overlapping literal matches from right to left within safe run segments,
  and refuses positional identities, stale paths, hyperlinks, fields, breaks,
  tabs, and unsupported text boundaries.
- `format_pptx_runs` and `format_pptx_paragraphs` target exact inspected paths
  plus original-text stale guards. Every guard is preflighted against the input
  snapshot before mutation. Fields, tables, default/end-run properties, raw
  XML, and positional paths remain excluded. Text longer than the 4,000-
  character guard is refused rather than targeted from truncated inspection.
- The run allowlist covers explicit bold/italic, 0.5-point size, underline,
  strike, RGB color, combined Latin/East Asian font, and explicit Latin, East
  Asian, and complex-script slots. Paragraph writes cover alignment, spacing
  before/after, and one point or percent line-spacing representation. Existing
  font metadata and compatible color transforms are retained; complex fills
  are not destructively collapsed to RGB. `underline=none` clears authored
  underline line/fill children that native PowerPoint can otherwise revive.
- Before serialization, each touched slide is canonicalized against its source
  tree with only selected `a:t`, `xml:space`, or requested direct-formatting
  slots normalized. Any other structural or attribute change fails the
  transaction. Only touched slide parts may change; allowlisted external
  hyperlinks and unrelated package content remain byte-preserved.
- DOCX, XLSX, and PPTX serialization pass a shared OPC preservation gate that
  rejects archive-comment, relative-order, stable ZIP-metadata, or unapproved
  part-payload drift. The gate normalizes only ZIP data-descriptor and Deflate
  tuning flags plus synthetic upper-half Unix permissions on DOS-created
  entries; encryption/security flags and DOS attributes remain significant.
  Allowed all-zero-match transactions return the exact input bytes.
- The native PPTX round-trip manifest requires Microsoft PowerPoint and WPS
  Presentation lanes for the typed formatting schema to remain open. Each
  verified lane is bound to the deterministic seed and native output by SHA-256
  receipts and package application metadata, and every fixture is exercised by
  typed formatting, semantic readback, and touched-part preservation tests.

## Known Limits

- Inspection and replacement currently cover `w:t` text in the main document
  body, including table cells.
- Headers, footers, notes, comments, fields, tracked changes, and text boxes are
  not yet addressable.
- Rendering is available, but automated semantic visual comparison is not. An
  agent or reviewer must inspect every returned PNG with `view_image`.
- Microsoft PowerPoint 16 and WPS Presentation 12 both pass the native PPTX
  corpus. WPS normalizes the seed width by 634 EMU while preserving height and
  every typed formatting invariant; the reviewed 1,000-EMU width tolerance and
  exact per-producer observation are stored in the manifest. Readiness is true,
  and the operation schema now includes exact typed run and paragraph
  formatting.
- LibreOffice rendering is a reproducible deployment baseline, not proof of
  pixel parity with Microsoft Word. Native Word rendering remains intentionally
  outside the portable runtime contract.
- Selector matching is intentionally case-sensitive for text and
  case-insensitive for style IDs. Run text must be contained within one
  inspectable run; cross-run text selection remains deferred.
- The generic selector grammar and broad formatting property surface remain
  deferred. The typed contract will grow only with interoperability fixtures.
- Theme mutation, character effects, borders, shading, numbering/style
  creation, and cross-run text selectors remain deferred.
- New properties are placed against known WordprocessingML run and paragraph
  property sequences, but existing malformed known-property order is preserved
  to avoid moving foreign extension children. A full ECMA-376 schema validator
  is not yet part of the runtime.
- XLSX formatting currently targets only cells already declared in worksheet
  XML. It does not create blank cells, write values or formulas, evaluate
  formulas, or mutate rich text, borders, conditional formatting, tables,
  charts, pivots, slicers, drawings, hyperlinks, validation rules, or sheet
  structure.
- The XLSX direct-style surface resolves effective style state for matching,
  but does not mutate workbook themes or named styles. Theme/indexed colors are
  inspectable as typed metadata; RGB selectors match only explicit RGB colors.
- LibreOffice Calc rendering is a portable print-layout baseline, not pixel
  parity with Microsoft Excel. Hidden sheets, print areas, formula refresh,
  pagination, and application-specific chart behavior require explicit review.
- PPTX rendering is a static LibreOffice baseline, not pixel parity with
  Microsoft PowerPoint. Animation playback, transition playback, morph behavior, video,
  SmartArt, 3D, theme substitution, and application-specific chart behavior
  require explicit review in the target presentation viewer.
- PPTX notes and comments are opt-in because they may contain review-only or
  sensitive context. Annotation inspection is relationship-aware and bounded,
  but rich comment-body formatting, comment mutation, notes mutation, and
  viewer-specific annotation rendering remain outside this batch.
- PPTX formatting readback is direct-only. It does not infer a textbox-wide
  font, size, color, bold, or italic state from the first run, and it does not
  resolve theme, layout, master, placeholder, list-style, or table-style
  inheritance. Direct picture blip effects are typed; inherited effects,
  general shape effects, WordArt, and raw XML are not exposed.
- PPTX inspection exposes bounded logical objects in shape-tree order. Paths
  prefer slide-unique `cNvPr.id` values and fall back to collision-free sibling
  positions when IDs are missing or duplicated. Nested group parentage, local
  z-order, authored EMU transforms, rotation, flips, alt text, graphic kind,
  and directly referenced relationship IDs are inspectable.
- PPTX resources retain slide/object owner paths while following internal
  dependencies such as layout, master, theme, chart data, media, and package
  parts. Records include relationship mode, resolved part, effective content
  type, byte size, and traversal depth. Master-to-layout catalog edges and
  nested slide back-references are excluded so a selected slide does not claim
  unrelated presentation structure. Object and resource output have explicit
  counts and truncation flags.
- PPTX selectors accept only exact object paths returned by inspection. They do
  not accept wildcards, descendant/sibling combinators, regular expressions,
  or raw property predicates. Paragraph and segment paths are read-only output
  identities and are not selector or edit targets in this batch.
- Structured interactions are read-only and bounded to 100 records per
  returned object and 2,000 per inspection window. Unsafe external targets and
  authored actions are surfaced with explicit markers and continue to block
  rendering. Text hover links use the same stable owner paths as click links.
  Relationship IDs are bounded in object, interaction, picture, and resource
  output while internal resolution retains the complete authored value.
- PPTX transition and animation output describes authored XML semantics; it
  does not simulate event dependency graphs, media playback, or final
  slideshow timing. Unknown presets retain typed identifiers without raw XML.
- PPTX editing remains deliberately narrow. Existing direct runs and paragraphs
  have a bounded formatting allowlist; shape-wide formatting, text creation or
  reconstruction, slide creation/reordering, tables, charts, media, notes,
  comments, fields, break/tab mutation, bullets, and dynamic effects remain
  deferred. Regex, global search, fuzzy paths, and destructive paragraph
  reconstruction are intentionally excluded.

## Verification

Focused tests cover split/ruby runs, table context, direct formatting readback,
conjunctive selectors, per-script fonts, paragraph layout, schema ordering,
formatting preservation, document-scoped first occurrence, transaction
failure, hyperlink boundaries, semantic text boundaries, tracked-change
rejection, path traversal, immutable uploads, storage-level atomic replacement,
remote artifact mirroring, exact render page windows, hard raster deadlines,
and malformed OPC/ZIP packages.

The direct PPTX formatting/selector batch passes 54 focused PPTX/tool tests,
the complete 167-test Office suite, and all 33 tool-schema warning tests.
Focused Ruff lint and format checks pass. The repository has no configured
Python typechecker; full-backend Ruff still reports two unrelated import-order
findings in `tests/test_threads_router.py` at lines 648 and 720.

The implementation also validated all 14 DOCX files under the reference
repository's `examples/word` corpus. An in-memory replacement against
`run-formatting.docx` preserved a valid package and the expected edited text.

The Docker renderer was exercised through the fixed-route proxy against all
three pages of `run-formatting.docx` at 120 DPI. Visual inspection confirmed
that Latin, CJK, emphasis marks, RTL placement, page flow, and clipping were
clean after adding the Noto CJK/emoji font set. A typed run-format and paragraph
alignment transaction was then rendered again; the selected text changed size,
color, underline, and alignment without disturbing surrounding layout.

The expanded selector/formatting batch was rendered over the same three-page
corpus. Direct per-script font matching and replacement, colored underline,
superscript-run targeting, all-caps, paragraph spacing, and indentation all
rendered as requested. The intentional paragraph reflow remained contiguous;
all three resulting pages were inspected without overlap, clipping, missing
glyphs, or unexpected page-count changes.

The XLSX batch adds focused tests for workbook metadata, typed range bounds,
style matching, styled blank cells, merged ranges, dates, formulas and cached
values, transactional no-match behavior, external-link refusal, base-style
preservation, cell-XF deduplication, package-part preservation, and the XLSX
renderer route/MIME/manifest contract. A formula-bearing worksheet test
confirms both `<f>` and cached `<v>` survive a style edit unchanged.

Post-implementation source review added regression coverage for malformed
number formats, relationship-addressed worksheet limits, significant worksheet
name whitespace, stable array-formula inspection, six-digit RGB selectors,
bounded cached-formula lookup, and relationship-addressed active content.
The follow-up review added Excel 4.0 macro-sheet rejection, existing-format
length validation, explicit alpha-insensitive `#RRGGBB` selector coverage, and
multi-cell array-formula cache preservation.
An in-memory inspection benchmark returned 5,000 formula cells in 0.184 seconds
after replacing repeated read-only stream scans with indexed cached-workbook
lookups.

The reference `cell-formatting.xlsx` corpus rendered as six Calc PDF pages at
120 DPI before and after two typed formatting operations. Every source and
edited page was inspected. Only the two targeted pages changed hashes; font,
fill, alignment, and number formats rendered as requested. The four untargeted
pages, including borders, formulas, links, merges, array formulas, and rich
text, retained identical page hashes. Page count and dimensions stayed at six
pages and 993x1404 pixels with no overlap, clipping, missing glyphs, or layout
regression.

All 28 `.xlsx` files in the reference examples corpus pass the VassilFlow
validator. Controlled style-edit smoke tests preserve conditional-formatting
nodes, sparkline extension markup, the complete package part set, and all 16
chart/drawing parts byte-for-byte. Pivot and slicer workbooks are detected and
refused before mutation as intended.

After the source-review hardening pass, the renderer image was rebuilt and the
same six-page workbook produced the prior baseline dimensions and SHA-256
digests on every page. A workbook with an external-link relationship targeting
a nonstandard package path was rejected with HTTP 422 before conversion. The
rebuilt sidecar also rejected a relationship-addressed Excel 4.0 macro sheet
with HTTP 422, while a valid workbook retained its baseline page hash.

The PPTX parser validated and inspected all 63 `.pptx` files in the reference
examples corpus, covering 463 declared slides. It resolved presentation order
through relationships, resolved every internal relationship target, accepted
the source corpus's effective default XML main content type, included
grouped-shape and table-cell text, and identified one OLE deck plus two decks
with safe HTTPS hyperlinks without dereferencing them. Sixty-two decks remain
renderable; the OLE deck is refused.

The rebuilt renderer produced all 21 requested pages from representative base,
merged-table, combo-chart, and morph/transition decks at 120 DPI. Every page
was nonblank and 1601x900. Direct visual review found clean framing, text,
tables, charts, and glyphs in the base/table/chart samples. The morph sample
rendered all five static slides but visibly retained overlapping text and
placeholders; the reference implementation's own issue scan independently
reported 23 text-overflow issues in that source deck, so it is retained as a
negative visual-QA fixture rather than a passing fidelity sample. Two CJK
slides rendered with complete glyph coverage.

A repeated two-slide table render produced identical PNG SHA-256 values and
the same pipeline fingerprint. A six-slide deck with slide 2 hidden initially
exposed LibreOffice's default five-page export. The explicit
`ExportHiddenSlides=true` contract restored all six pages and the rebuilt
sidecar emitted `source_slide` values 1 through 6. Visual inspection confirmed
that the hidden slide retained its original layout and content.

Live proxy requests rendered both HTTPS-hyperlink decks with HTTP 200 while
the OLE deck remained blocked with HTTP 422 before conversion. The clickable
picture slide rendered cleanly without dereferencing its hyperlink. The
Gateway client parsed a real PPTX render archive, verified its versioned,
digest-bound manifest, and enforced the source-slide mapping.

The object-identity follow-up re-inspected the same 63-deck corpus: 463 slides,
4,153 logical objects, 1,921 owned resource records, three real grouped objects,
and eight 3D-model wrappers. Every returned object path was unique within its
slide, every internal resource had an effective content type and byte size,
every owner remained under its selected slide path, and no inspection window
was truncated. Direct
review of the real group, chart, embedded-data, image, and video cases confirmed
that nested owners stay attached to the originating logical object.

The direct-formatting and typed-selector follow-up inspected the same 63 decks
with formatting enabled: 463 slides, 4,153 objects, 3,625 objects with direct
shape style, 3,545 text bodies, 4,717 paragraphs, and 4,544 source-order text
segments. No deck failed or exhausted a formatting bound. One stable object
path from every deck was exact-selected in a fresh inspection; all 63 returned
exactly one matching path and no duplicate path was observed.

The formatting follow-up rebuilt the renderer sidecar and rendered three
typography slides plus two shape-style slides at 120 DPI. All five pages were
nonblank, mapped to their same-numbered source slide, and measured 1601x900.
Direct inspection of the shape-style deck matched solid, scheme, opacity,
none, pattern, linear-gradient, radial-gradient, and per-stop gradient JSON to
the rendered samples. The typography fixture still shows overflow and extreme
character-spacing behavior on its first two LibreOffice-rendered slides; the
third RTL/complex-script slide and both shape-style pages remained framed and
legible. This read-only batch does not classify those renderer-specific
typography differences as a formatting-readback pass.

Live render regression then re-rendered the editable flowchart group and combo
chart baselines at 120 DPI. Both manifests mapped the requested source slide,
both pages were nonblank at 1601x900, and direct image review found intact
connectors, z-order, labels, chart legends, framing, and clipping behavior.

The slide-metadata, interaction, and picture-formatting follow-up re-inspected
all 63 reference decks and 463 slides with formatting enabled. Every slide
resolved a layout; 128 slides exposed a direct background (122 solid and six
gradient). The parser returned all seven authored interactions without
truncation: three external URL records, one internal slide jump, one show jump,
and two media actions. Shape-level and run-level duplicates retained distinct
owner paths. Picture readback found six crops, four direct effect sets, and one
authored compression state. No interaction owner escaped its logical object,
and no deck failed inspection. The read-only batch passes 78 focused PPTX,
tool, and rendering-contract tests plus Ruff check and format verification.

The annotation and dynamics follow-up read the reference implementation's
notes, legacy-comment, modern-comment, transition, animation, query, and batch
emitter sources directly. A deck authored by that implementation confirmed the
actual notes part, legacy author list, modern GUID author list, resolved thread,
and nested reply schemas against VassilFlow's typed output. The source corpus
contains no authored notes or comments, so this generated interoperability deck
supplements the bounded unit fixtures rather than being treated as a broad
annotation corpus.

All 63 reference PPTX files and 463 slides then passed dynamics inspection.
The scan returned 218 selected transition choices across standard, 2010, 2012,
and 2015 extension schemas plus 191 deduplicated authored animation effects;
all 191 target shape IDs resolved to stable VassilFlow object paths. Seven
motion paths were retained as bounded typed records. No deck failed or exhausted
an animation bound.

The preservation follow-up adds a shared OPC gate and focused container-drift
tests. DOCX, XLSX, and the narrow PPTX editor protect archive comments,
relative entry order, stable ZIP metadata, and unapproved part payloads. PPTX
also compares canonical source and result slide trees before serialization so
the package allowlist cannot hide an unsupported mutation inside a touched
slide part.

Two independent source reviews then compared the VassilFlow implementation
against the reference notes, comments, animation, query, package, DOCX, and
XLSX paths. The hardening pass added bounded annotation source scans and author
maps, numeric legacy-author identity, animation `grpId` deduplication, nearest
wrapper delay semantics, easing/restart/build metadata, authored-ID paths,
markup-compatibility requirement evaluation, graph-wide DOCX relationship
validation, DOCX structural preflight, strict XLSX declared-sheet resolution,
shared XLSX inspect text budgets, exact no-op package returns, and compatible
ZIP data-descriptor preservation.

The first PPTX write batch then read the reference implementation's actual
find/replace, set-dispatch, shape-set, and shape-property sources. VassilFlow
ports only exact authored-shape paths, paragraph-local literal matching,
right-to-left application, and run-preserving text mutation. Regex, global
search, fuzzy selectors, destructive shape-text reconstruction, and writes to
notes, comments, tables, charts, media, formatting, or dynamic effects remain
excluded.

The focused PPTX engine suite passes 61 tests, the Office tool suite passes 23,
and the tool-schema warning suite passes 33. The complete Office-focused run
passes 215 tests with one skipped. An in-memory write smoke covered all 63
reference decks: 62 edited and validated with exactly the targeted slide part
changed, while `ppt/ole/ole-embed.pptx` was refused for its embedded-object
risk as designed. No compatible deck failed or lacked a stable text target.

Final visual QA changed `$99` to `$89` in authored shape
`/slide[3]/shape[@id=100010]` of `textboxes-basic.pptx`. Inspect readback kept
the direct shape and run formatting unchanged, package comparison found only
`ppt/slides/slide3.xml` changed, and both 120-DPI renders mapped to source slide
3 at 1601x900. Direct image review found no reflow, clipping, overlap, font, or
background regression; the pixel diff was confined to a 21x30 box around the
changed glyph (354 pixels, 0.024568 percent of the page).

The reference corpus passes again with 15 DOCX files, 28 XLSX files, and all 63
PPTX files covering 463 slides. Dynamics output remains 218 transitions and
191 deduplicated animation effects, with all target IDs resolved, seven bounded
motion paths, and no truncated inspection window.

The full backend run reports 5,841 passed and 38 skipped. Its 11 failures match
the pre-existing baseline: nine Windows tests cannot create symlinks without
the required host privilege, one setup-document phrase guard is already out of
sync, and one external-product token guard flags an older tracked internal
audit. No Office test fails in the full run.

The native PPTX corpus adds a deterministic two-slide, eight-object seed with
mixed runs, paragraph alignment and spacing, direct shape fill/line, text-box
margins and anchoring, and Latin, CJK, Greek, and Arabic text. The generator
first exercises VassilFlow's exact-path edit, then the Microsoft PowerPoint
16.0 build 17928 lane opens and saves the exact seed through COM. The fixture
receipt binds input and output hashes and confirms `Microsoft Office
PowerPoint` package metadata. Rebuilding the seed is byte-exact.

Semantic inspection of the seed and native fixture matches every declared
run, paragraph, style, margin, anchor, object identity, and text invariant.
The native fixture also remains editable with only
`ppt/slides/slide1.xml` changing. This test exposed PowerPoint's Deflate tuning
flags and zero DOS-entry external attributes; Python's ZIP writer clears the
former and synthesizes unused upper-half Unix permissions for the latter. The
shared OPC guard now normalizes only those container details while retaining
security flags and DOS attributes as meaningful metadata.

A second live cycle edited `Final` to `Ready` with VassilFlow, reopened and
saved the result in PowerPoint, then validated and inspected the native output.
All semantic invariants survived. At 120 DPI, the seed and first PowerPoint
fixture were pixel-exact on both 1601x900 slides. After the edit/reopen cycle,
slide 2 remained pixel-exact and slide 1 differed only inside the sentinel text
box: 8,794 pixels in bounding box `(879, 232, 1426, 270)`. Direct image review
found no clipping, overlap, missing glyph, style, or layout regression.

The corpus/OPC focused run passes 11 tests, the complete Office-focused run
passes 222 tests with one skipped, and all 33 tool-schema warning tests pass.
The WPS lane was then produced through the registered `KWPP.Application` COM
server using WPS Presentation 12.0 build 12.1.0.26886. Its receipt reports WPS
package metadata, binds the unchanged seed hash to the native output, and is
written as UTF-8 without a BOM across Windows PowerShell versions. The first
strict corpus run exposed the PowerShell 5 BOM behavior; the harness was fixed
and the receipt regenerated rather than weakening JSON parsing.

WPS expands the package from 40 to 51 entries by adding explicit ZIP directory
entries and `docProps/custom.xml`, and removes the seed printer-settings part.
The validated output contains no risky feature. Its slide width is 12,191,365
EMU versus the seed's 12,191,999 EMU, with the 6,858,000-EMU height unchanged.
This 634-EMU native normalization is recorded exactly and remains below the
reviewed 1,000-EMU corpus tolerance.

VassilFlow edited the WPS fixture with only `ppt/slides/slide1.xml` changing,
then WPS reopened and saved that edit. Every run, paragraph, style, margin,
anchor, object identity, Unicode string, and slide-count invariant survived.
Both WPS renders were clean at 1600x900. The edited second slide stayed
pixel-exact; the first differed only inside the sentinel text box: 8,771 pixels
in bounding box `(878, 232, 1425, 270)`. Both required producer lanes are now
verified and `formatting_readiness.ready` is true. At that checkpoint, the
operation schema had not yet expanded beyond `replace_pptx_text`.

The typed PPTX formatting batch then read the reference implementation's actual
shape-set, run-format helper, schema-order, and shape-property sources. The
ported subset is deliberately smaller: exact direct `a:r` and `a:p` targets,
explicit boolean and enum values, RGB text color, script-aware font slots,
font size, paragraph alignment/spacing, and schema-aware child insertion. Raw
property aliases, whole-shape text rebuilding, default-run or bullet XML
injection, implicit table/run materialization, presentation-wide selectors, and
generic set/remove commands remain excluded. Effective theme inheritance,
fields, tables, highlights, RTL, and broader text effects remain deferred
behind separate fidelity contracts.

An independent source review caught two preservation gaps before release. The
first implementation recreated font and fill children, which could drop WPS
`panose` metadata or an authored alpha transform. Font writes now mutate only
`typeface`; RGB writes preserve compatible solid-color transforms and reject
destructive conversion of complex fills. The original and edited trees mask
only those narrow values, so metadata loss fails the canonical invariant.
`underline=none` also clears underline line/fill children that native PowerPoint
can otherwise render again. Regression tests cover font metadata, alpha,
underline cleanup, complex-fill refusal, stale preflight, long/truncated target
refusal, mixed text/format transactions, hyperlink preservation, and unrelated
mutation rejection.

All formatting target guards are resolved against the original transaction
snapshot before the first edit. The public contract therefore uses text copied
from formatting-enabled inspection, not a value predicted after an earlier
operation. Exact no-op formatting returns the original package bytes. Verified
PowerPoint and WPS fixtures both pass typed run/paragraph writes with only
`ppt/slides/slide1.xml` changing; a same-font write on the WPS `Beta` run keeps
its authored `panose=02040502050405020303` before and after native reopen.

Live native QA reopened the formatted fixtures in Microsoft PowerPoint 16.0
build 17928 and WPS Presentation 12.0 build 12.1.0.26886. Both retained the
requested 26-point, non-bold italic run with RGB `#1F4E79`, plus justified
paragraph alignment, 120-percent line spacing, four-point space before, and
ten-point space after. LibreOffice/PDFium renders at 120 DPI changed only slide
1 inside bounding box `(109, 190, 766, 508)`: 15,293 pixels for the 1601x900
PowerPoint lane and 15,386 for the 1600x900 WPS lane. Slide 2 stayed
pixel-exact in both lanes, and direct review found no overlap, clipping, missing
glyph, or unrelated style change.

Installing WPS can register `PowerPoint.Application` to its compatibility
server. The native harness now detects that condition, starts the installed
Microsoft `POWERPNT.EXE` in a private automation process, refuses to attach if
PowerPoint is already open, and leaves COM registration unchanged. Both named
producer modes pass after this hardening.

Final verification passes 106 focused PPTX/corpus/tool tests, the complete
Office-focused run with 239 passed and one existing skip, and all 33 tool-schema
warning tests. Ruff check and format verification pass for every changed Python
file, the native PowerShell harness parses and runs in both producer modes, and
the scoped diff has no whitespace errors.

## Live agent acceptance (2026-07-14)

The typed PPTX formatting path was exercised through the running LangGraph API
with `gpt-5-3-codex-spark`, using an isolated version-19 config overlay so the
developer's local `config.yaml` and secrets remained untouched. The first live
attempt exposed model-generated union contamination: inert fields from text
selectors appeared inside exact PPTX object-path selectors. Provider tracing
confirmed that the submitted arguments were not being rewritten in transport.

The public schema now states the exact PPTX operation shapes, and operation
parsing narrowly removes only `contains_text=null`, `occurrence=null|all`, and
`require_match=true|null` from nested exact selectors. Non-null text queries,
non-default occurrence values, false match requirements, arbitrary keys, and
all direct-selector extras remain strict validation errors.

A fresh natural-language run completed inspect, one successful typed edit,
re-inspection, and two-slide rendering without a corrective prompt. Acceptance
thread `66f590d0-e082-4749-8eda-7c59f0a96c49` used run
`54c72c46-1652-47a5-a6a7-63f71c418ab8`. The generated PPTX and both rendered
pages were byte-identical to the accepted native round-trip corpus:

- PPTX SHA-256: `55931ED2F0C1278D538BF12EC0678F1605BE46F0B95C75A53DA2DC3AD8F6EC23`
- Slide 1 PNG SHA-256: `B80A15F4B01120685BD44952FDE6E2E2EEB6D9500491C1D4B18A317881C74314`
- Slide 2 PNG SHA-256: `762F3C48505FB9F023ECCAA6B734A2B2ED42007FF71CE0BD7EF5A0173D8EBF85`

Independent review of the actual PNGs found no clipping, overlap, blank slide,
or unrelated visual change. An interactive browser session was unavailable in
the test environment, so UI clicking was not automated; the production API,
workspace-change, renderer, and artifact paths were all exercised. Existing
version-18 installations must run `make config-upgrade` (or the documented Git
Bash fallback) before the Office tools are exposed.

## Presentation-time visual review gate (2026-07-15)

UI acceptance thread `1179b123-4f22-4469-9031-883a3a4daffd` successfully used
`office_inspect`, one `office_edit`, re-inspection, `office_render`, and
`present_files`. Semantic readback matched both requested formatting targets,
only `ppt/slides/slide1.xml` changed, both rendered pages matched their manifest
hashes, and independent image review found no clipping, overlap, missing glyph,
or unrelated visual change. The agent did not call `view_image` before
presentation because its active model did not expose that tool.

The active `gpt-5-3-codex-spark` configuration correctly declares
`supports_vision=false`. A direct, redacted probe against the same Codex
Responses endpoint returned HTTP 400 with `Model 'gpt-5.3-codex-spark' does not
support image inputs`. OpenAI's documented Responses image format uses
`input_image`, while the Codex app-server separately accepts `image` and
`localImage` turn items. Neither contract justifies pretending that a
text-flattened provider reviewed pixels.

The runtime now enforces a hash-backed gate at presentation time. Every Office
deliverable needs current render manifests covering every page. A vision model
must call `view_image` in a prior model step; the middleware records a page hash
only when the image payload is injected into that model, and `present_files`
rejects missing, stale, same-step, or incomplete review. A text-only model can
still present the file so the user can download and review it, but the tool
returns `visual_review_status=external_review_required` and explicitly forbids
claiming visual QA passed. The gate also validates current source and page
hashes, manifest page coverage, and Gateway-visible page files.

Verification passes 101 focused review/tool tests, 233 Office tests, and 193
agent state, middleware, schema, and model-resolution tests. A live smoke test
against the accepted UI artifact confirmed the external-review warning and
false-pass guard, and the restarted Gateway loaded the new reducer-backed state
with all three Office tools available.

## Typed direct shape formatting (2026-07-15)

The shape-write batch was based on direct comparison with the reference
implementation's `Set.Shape`, `ShapeProperties`, `Fill`, `Effects`, and
selector/resolution sources at upstream commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8`. VassilFlow already had the
necessary read-only style inventory, stable nested object paths, native
PowerPoint/WPS corpus, and canonical preservation gate. The compatible subset
is therefore a typed operation over exact authored-ID shape paths with an
`expected_name` stale-state guard: direct solid or no fill, direct line RGB or
no fill plus width/cap/preset-dash/join, text-box margins in points, and
top/middle/bottom vertical anchoring.

The generic selector and set/remove command model, raw XML mutation, and
implicit theme fallback are not suitable for the VassilFlow tool boundary.
Gradient, pattern, and image fills; custom dash, compound/alignment, arrowhead,
and connector controls; geometry, z-order, shape creation, slide
creation/reordering, and table/chart/media writes remain deferred until each
has its own interoperability corpus.

Every shape target and expected name is resolved against the original package
before any operation mutates the document. Missing or duplicated authored IDs
cannot be used for writes: inspection gives those objects collision-free
positional paths, while the shape formatter accepts authored-ID paths only.
Existing complex fills are refused instead of being collapsed. A width-only
request cannot silently create a default black line; callers must specify the
new line fill in the same operation. RGB changes preserve compatible color
transforms such as alpha, unrelated DrawingML stays protected by the canonical
invariant, and an exact no-op returns the original package bytes. Text-box
insets retain OOXML's signed semantics within a bounded -4032 to 4032 point
range, including the small negative values emitted by native producers.

Independent comparison of both implementations found three release blockers
in the first draft. DrawingML creation now derives the matching Strict or
Transitional namespace from the PresentationML context and rejects mixed
target structures. The no-fill canonical mask replaces the fill slot in place,
and every edited shape is revalidated for schema order after mutation. Solid
color structure for every target is also preflighted before the first target is
changed, so a later malformed color cannot leave an earlier in-memory target
partially edited. Regression tests inject mixed namespaces, reordered
`noFill`, duplicate colors, duplicate authored IDs, and negative insets.

Native QA formatted deterministic Microsoft PowerPoint and WPS fixtures, then
reopened and saved each result in PowerPoint 16.0 build 17928 and WPS
Presentation 12.1.0.26886. Both producers retained fill `#5B9BD5`, line
`#A5A5A5` at 4.25 points, text-box margins of 30/18/12/6 points, top vertical
anchoring, all target text, and the unrelated Georgia run font. Package
validation and semantic reinspection passed after both native saves. The
PowerPoint lane changed from input SHA-256
`b2d55c5cf5392510a827538315840803c2dc675942d4ed306cfec4182f26bda9` to
native output
`87c3576f992d4fb7dca25df806e90f962fbacba70b8b3af2ebebc474afbe399b`;
the WPS lane changed from
`6a1158b1f1e6569419a8d30c03fbe201ebc70d3ecb71a9a303b0a895ccc17cc8` to
`4059d04cbdc2326959019dac5a4cb63726c1149f926e8ec550cdf73345e690b4`.

LibreOffice/PDFium rendered every baseline and native result at 120 DPI. The
PowerPoint lane changed 140,746 pixels on slide 1 inside
`(831, 354, 1390, 612)` and 11,523 pixels on slide 2 inside
`(166, 443, 747, 638)`. The WPS lane changed 140,399 pixels on slide 1 inside
`(831, 354, 1389, 612)` and 11,700 pixels on slide 2 inside
`(166, 443, 746, 638)`. Those bounds cover only the requested style shape and
margin/anchor text box. Direct review of all final pages found no clipping,
overlap, missing glyph, blank page, or unrelated visual change.

Color transforms beyond alpha are returned as a bounded ordered list with raw
OOXML values and percent/degree interpretations. Shapes with a missing or empty
authored name can be targeted only with the matching required `null` or empty
guard; an inspection-truncated name still fails closed.

Final verification passes 119 focused PPTX/corpus/tool tests, the complete
Office suite with 245 passed, and all 33 tool-schema warning tests. Ruff check
and format verification pass for the changed Python surface, and the scoped
diff has no whitespace errors.

## Typed line style and color transforms (2026-07-15)

The follow-up audit fetched `origin/main` again and confirmed current upstream
commit `4ba79f0b984e141f57f58d4398ba2df29e8187e8`. The `Fill`, `ShapeProperties`,
and `Effects` blobs remain identical to the previously audited checkout. The
comparison read the actual color-transform emitter/parser, shape line setter,
connector line setter, and line-style readback in `NodeBuilder`.

VassilFlow already exposed direct line cap, dash, join, compound, alignment,
and arrow metadata read-only. The compatible write subset is deliberately
smaller: flat/round/square cap, the eleven DrawingML preset dash values, and
round/bevel/miter join with an optional bounded miter limit. Exact authored-ID
shape paths, original-name preflight, no implicit black line, schema-aware
insertion, post-mutation order validation, and the canonical subtree invariant
remain mandatory. A missing or empty authored name is now represented by an
explicit required `null` or empty guard; truncated names remain untargetable.

Read-only color output now preserves authored order for `lumMod`, `lumOff`,
`shade`, `tint`, `satMod`, `satOff`, `hueMod`, and `hueOff`. Each record keeps
the raw integer plus a percent or degree interpretation, is independently
bounded, and does not alter the existing alpha/opacity field. RGB writes still
preserve all compatible transform children whether or not they are returned.

Raw custom-dash XML, generic property dictionaries, destructive fill fallback,
and width/style requests that synthesize a black line are not suitable.
Compound/alignment, arrowhead and connector writes, gradients, patterns,
picture fills, effects/3D, geometry, and z-order remain deferred. Multiple
authored dash or join choices and invalid miter limits fail preflight before
any target is mutated.

Native QA applied only `square` cap, `large_dash`, and a miter join at 800
percent to `VF_RT_STYLE`, preserving its authored line RGB `#E04B42`, width
31,750 EMU, fill, text, and geometry. PowerPoint 16.0 build 17928 reopened
input SHA-256
`cb4d9cef7dcf3d94e80e72ce899a57d627983631ecbd8207a9219ae8d89aedc9`
and produced
`346b8c0a1e503c073d56a3cf73965f4664534760b6a6798c59d96daf68f3a682`.
WPS Presentation 12.1.0.26886 reopened
`fca41210ec033f5a1453763a889830ebce5dce760f370640e8a993ff4f73d7c5`
and produced
`908025e778ebf6536af383b0ae4a1d3ea711ad238c9ef44e74f83fd33b15cfea`.
Both native outputs validated and retained every requested value; every
non-target object matched its pre-native semantic inspection.

LibreOffice/PDFium rendered both baseline/native pairs at 120 DPI. PowerPoint
slide 1 changed 6,001 pixels (0.416476 percent) inside
`(833, 355, 1388, 610)`; WPS slide 1 changed 6,011 pixels (0.417431 percent)
inside `(832, 355, 1387, 610)`. Both slide 2 renders were pixel-exact. Direct
review found the requested dashed outline clean and consistent across both
producers, with no clipping, overlap, blank content, or unrelated visual
change.

Final verification passes 125 focused PPTX/corpus/tool tests, the complete
Office suite with 251 passed, and all 33 tool-schema warning tests. Ruff check,
format verification, and the scoped whitespace diff gate pass. The restarted
Gateway reports healthy and its live schema contains all six direct line fields
with `expected_name` still required and explicitly nullable.

## Typed line and connector classification (2026-07-15)

This batch compares the current VassilFlow implementation directly with
upstream commit `4ba79f0b984e141f57f58d4398ba2df29e8187e8`. The inspected sources are
the shape and connector setters in `ShapeProperties` and `Set.Shape`, the line
end parsers in `Fill`, and the shape/connector readback in `NodeBuilder`.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Connector inventory, authored `cNvPr.id` paths, direct `a:ln` inspection, strict/transitional namespace handling, schema-order checks, transactional preflight, and canonical preservation | Reuse the existing infrastructure. |
| Port | Typed compound line (`single`, `double`, `thick_thin`, `thin_thick`, `triple`), pen alignment (`center`, `inset`), and typed head/tail line ends with independent type, width, and length | Open these only through exact authored-ID line targets for shapes or connectors, with the required original-name guard. |
| Not suitable | Generic property dictionaries, raw XML/custom-dash replay, implicit black-line creation, and connector endpoint mutation (`from`/`to`) | Keep these outside the VassilFlow tool boundary. |
| Defer | Gradient/pattern/image line fills, effects and 3D, custom geometry, connector routing, object creation, and z-order | Require dedicated native corpus and visual QA before any write surface. |

The reference connector setter supports compound and arrowheads but does not
write line alignment, even though `algn` is a valid `CT_LineProperties`
attribute. VassilFlow will use one typed line contract for both authored shapes
and connectors because both own the same direct DrawingML line element. It will
not inherit the reference implementation's destructive fallback that creates a
black line when style metadata is requested without an authored line or an
explicit fill in the same operation.

At classification time, the native corpus had no connector. A connector authored through the
deterministic seed and accepted by both Microsoft PowerPoint and WPS
Presentation is therefore a release gate for this batch. Gradient, effects/3D,
and geometry remain closed even after that connector corpus is added.

### Implementation and acceptance

The deterministic corpus now contains `VF_RT_CONNECTOR` at the stable path
`/slide[2]/connector[@id=5]`. Its baseline direct line has RGB `#4472C4`, a
3-point width, double compound style, centered pen alignment, a small/medium
diamond head, and a large/large triangle tail. The rebuilt seed SHA-256 is
`67cb6a6ff4eb03453edad472ebe4b7a215687b9bcbf9fb40f05d5bc53e6f8b4d`.
PowerPoint 16.0 build 17928 produced corpus fixture SHA-256
`aac104eb949a01fc7158ce7477cb611464f299ec6c703323df5b1611abd6745d`;
WPS Presentation 12.1.0.26886 produced
`38f7de1013eb35920a99fcb74163fb45244b7583a2960ed3504618ec7b19350e`.
Both native fixtures retain every baseline line field and the same authored-ID
path.

The new `format_pptx_lines` operation accepts exact authored-ID shape or
connector paths plus the required original `expected_name`. It reuses direct
solid/no-fill, width, cap, preset dash, and join fields, then adds canonical
compound values (`single`, `double`, `thick_thin`, `thin_thick`, `triple`),
`center`/`inset` alignment, and typed head/tail records. Line-end type is one of
`none`, `triangle`, `stealth`, `diamond`, `oval`, or `arrow`; width and length
are independent `small`, `medium`, or `large` fields. A size-only request needs
an existing line end, and a line that does not exist can be created only when
the same operation supplies an explicit fill.

All targets, original names, existing line enums, direct fill structure,
DrawingML namespace consistency, child order, dash/join choices, miter limits,
and duplicate head/tail elements are checked before the first mutation. The
canonical preservation gate masks only the requested direct line slots on
`p:sp` or `p:cxnSp`; shape fill/text/geometry and connector routing remain
protected. Strict PresentationML creates Strict DrawingML line-end children,
and an exact no-op returns the source package bytes.

Acceptance changed each connector to square cap, large dash, miter join at 800
percent, triple compound, inset alignment, a large/small stealth head, and a
medium/large oval tail. VassilFlow output SHA-256 values were
`d6bb7622f38c4cb6959851214520f4e3e0bee7bb11aa99edc2b7c48ed058263e`
for the PowerPoint lane and
`20557bb469c193359a72c3013e821eab4fe419fe375e1dba425212c001ad884e`
for the WPS lane. Native reopen/save produced
`1cedf309ecc0d7446283291aa2a9a5860125f08dd795aaa6fb05ca28e167c883`
and `be1f33bdbcb82797d8dbb10c8fe86d44d5308f1a4ceaf61da729312e3e8a71bb`
respectively. Both outputs validate, preserve connector geometry and slide
size, retain every requested line field, and have no non-target semantic
differences.

LibreOffice/PDFium rendered baseline and native output at 120 DPI. PowerPoint
slide 2 changed 8,190 pixels (0.568395 percent) inside
`(847, 482, 1421, 668)`; WPS slide 2 changed 8,195 pixels (0.569097 percent)
inside `(846, 482, 1420, 668)`. Both slide 1 renders are pixel-exact. Direct
review confirms the requested dashed triple connector with stealth and oval
ends, with no clipping, overlap, blank content, or unrelated visual change.

Verification passes 134 complete PPTX engine/corpus/tool tests, the full Office
suite with 260 passed and one existing Starlette deprecation warning, and all
33 tool-schema warning tests. Ruff check and formatting pass for the changed
Python surface. The restarted Gateway is healthy, and its live tool schema
contains `format_pptx_lines`, all ten direct-line fields, and required
`path`/`expected_name` target guards. Gradient and non-solid line fills, custom dash, effects/3D,
geometry, routing/endpoints, object creation, and z-order remain deferred for
their own native corpus.

## Typed linear gradient classification and acceptance (2026-07-15)

The gradient batch fetched `origin/main` and confirmed the audited upstream
commit remains `4ba79f0b984e141f57f58d4398ba2df29e8187e8`. Direct comparison read the
actual gradient builder and normalization logic in `Background`, the shape
fill application and raw replay in `Fill`, shape and connector setters in
`ShapeProperties` and `Set.Shape`, semantic readback in `Helpers.RunFormat`,
and object inventory in `NodeBuilder`.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Bounded gradient inspection, exact stop positions, color/alpha readback, linear/path metadata, authored-ID shape and connector paths, namespace/order checks, transactional preflight, canonical preservation, and the native harness | Reuse the existing infrastructure. |
| Port | Typed direct RGB linear gradients with 2-32 strictly increasing stops, optional per-stop opacity, explicit angle/scaling, and explicit rotate-with-shape semantics for shape or line fill | Open through the existing `format_pptx_shapes` and `format_pptx_lines` contracts. |
| Not suitable | String gradient grammar, raw gradient XML, implicit scheme-color fallback, clamping or duplicating malformed stops, and destructive replacement of pattern/image/group fills | Keep these outside the VassilFlow tool boundary. |
| Defer | Path/radial tuning, gradient flip/tile metadata, pattern/image fills, effects/3D, geometry/routing, object creation, and z-order | Require separate corpus and visual acceptance. |

The typed model requires every semantic choice needed to build deterministic
DrawingML. Stop positions and opacity use 0.001-percent precision; angle uses
the native 1/60000-degree unit and must remain in `[0, 360)`. Existing gradient
fills are writable only when they contain exactly an ordered `gsLst` plus
`lin`, direct RGB stop colors, and at most one alpha transform per stop.
Scheme colors, path gradients, unknown attributes, mixed namespaces, duplicate
or unordered stops, and non-semantic tuning fail preflight before any target
is changed. A semantically exact request preserves the package byte-for-byte.

The deterministic corpus adds `VF_RT_GRADIENT` at
`/slide[1]/shape[@id=7]` and `VF_RT_GRADIENT_CONNECTOR` at
`/slide[2]/connector[@id=6]`. The shape carries three stops, a custom 37.5
percent middle position, 85 percent middle-stop opacity, a 37.5-degree angle,
scaling, and rotate-with-shape. The connector carries a separate three-stop
direct line gradient. Seed SHA-256 is
`4fe034e708a6bca7e48f0b0aa053fde2acfca9e54ab57328fabf4d2b5dc41d5d`.
PowerPoint 16.0 build 17928 produced fixture SHA-256
`d4d341c3eb63ab755c62831d213938148d91aebe52f1eb0b8913b53daa81dc22`;
WPS Presentation 12.1.0.26886 produced
`5a8696a56176fd73167d7b814e9f7783eca292c2d979dcfd34fd8aa749e5f6da`.
Both fixtures validate and retain every gradient field without semantic drift.

Write acceptance changed the shape to stops at 0, 42.5, and 100 percent with
70 percent opacity on the middle stop, a 125-degree unscaled gradient, and
rotate-with-shape disabled. It changed the connector to stops at 0, 30, and
100 percent with a 180-degree scaled gradient. VassilFlow output SHA-256 values
were `c312b31161805207eb5cc0e7197f6a0aea9ab18b9997a08c71219ecd67257dbb`
for the PowerPoint lane and
`af7de2133cc1a3a37d6c65c84a10204fe655fe6b000f756fb2a4b84403014079`
for the WPS lane. Native reopen/save produced
`c138879ee1478c4e3cba011fcaf52360555828e55d2421ac8da42ec36b97b79c`
and `879091881ea18aeda5271e84a3914081342214dda8a557e5fc0fa800bec0dcb8`
respectively. Both native outputs validate, preserve every requested gradient
field, retain shape text/line/geometry and connector geometry/width, and have
no non-target semantic differences.

LibreOffice/PDFium rendered baseline and native output at 120 DPI. PowerPoint
slide 1 changed 81,336 pixels (5.644805 percent) inside
`(835, 639, 1386, 800)` and slide 2 changed 5,470 pixels (0.379624 percent)
inside `(858, 733, 1405, 743)`. WPS slide 1 changed 81,042 pixels (5.627917
percent) inside `(835, 639, 1385, 800)` and slide 2 changed 5,469 pixels
(0.379792 percent) inside `(858, 733, 1405, 743)`. Direct review found the
requested gradient changes only, with no clipping, overlap, blank content, or
unrelated visual drift.

Verification passes 143 focused PPTX/corpus/tool tests, the complete Office
suite with 269 passed and one existing Starlette deprecation warning, and all
33 tool-schema warning tests. Ruff check and formatting pass for the changed
Python surface. No local secrets or runtime configuration are needed for this
batch; `config.yaml` and `.env` remain untouched. The restarted Gateway is
healthy at `http://localhost:2026/`, and its live `office_edit` tool-call schema
contains the gradient stop, linear geometry, and expanded fill definitions.

## Typed radial gradient and preset geometry acceptance (2026-07-15)

This batch fetched the OfficeCLI reference again at commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8` and read the actual path-gradient
builder in `PowerPointHandler.Background.cs`, the geometry and effect setters
in `PowerPointHandler.ShapeProperties.cs` and
`PowerPointHandler.Effects.cs`, and the corresponding readback in
`PowerPointHandler.NodeBuilder.cs`. The reference maps radial and path fills to
`a:path` plus `a:fillToRect`. Its effect, 3D, and custom-geometry paths still
contain broad raw-XML fallbacks and implicit defaults, so those paths are not a
suitable VassilFlow write contract.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Read-only linear/path gradient metadata, preset/custom geometry identity, authored-ID shape paths, strict/transitional namespace handling, schema-order validation, transactional preflight, canonical preservation, and native PowerPoint/WPS harness | Reuse the existing infrastructure. |
| Port | Typed direct-RGB radial circle gradients with an explicit balanced focus rectangle, plus a bounded preset-geometry allowlist for unadjusted authored shapes | Open these through exact authored-ID `format_pptx_shapes` targets with the required original-name guard. |
| Not suitable | Raw gradient/effect/geometry XML, generic property strings, scheme-color fallback, non-circle path gradients, path gradients on lines, custom geometry replacement, and silent adjustment reset | Keep these outside the tool boundary. |
| Defer | Pattern/image fill, effects/3D, custom geometry and adjustment formulas, connector routing/endpoints, object creation, and z-order | Require dedicated source corpus and native visual acceptance before any write surface. |

The radial model requires 2-32 strictly increasing RGB stops, optional
per-stop opacity, `path=circle`, all four `fillToRect` edges at 0.001-percent
precision, opposing edges that sum exactly to 100 percent, and an explicit
rotate-with-shape choice. Line and connector models reject path geometry and
remain linear-only. Existing gradients are writable only when their ordered
children and all stop, color, alpha, path, and rectangle metadata match this
contract. Unknown attributes, mixed namespaces, comments, raw content,
unbalanced rectangles, and non-circle paths fail before any target is changed.

Preset geometry accepts `rect`, `roundRect`, `ellipse`, `triangle`,
`rtTriangle`, `diamond`, `parallelogram`, `trapezoid`, `pentagon`, `hexagon`,
`heptagon`, or `octagon`. The source must contain exactly one `prstGeom`, with
either no child or one empty `avLst`. `custGeom`, authored `a:gd` adjustments,
unknown metadata, and mixed geometry choices fail closed. The writer changes
only the `prst` attribute; the preservation gate masks only that attribute and
continues to protect transform, fill, line, text, and adjustment structure. A
semantic no-op returns the exact source bytes.

The deterministic corpus now has three slides and 14 objects. It adds
`VF_RT_PATH_GRADIENT` at `/slide[3]/shape[@id=3]`, with a three-stop radial
circle gradient and focus rectangle 35/25/65/75 percent, and
`VF_RT_PRESET_GEOMETRY` at `/slide[3]/shape[@id=4]`, with an unadjusted
`roundRect`. Seed SHA-256 is
`2833a5364890adc79b5d22bd74bcffcf6de5acb98cf9dcdf463967683b95c14f`.
PowerPoint 16.0 build 20131 produced corpus fixture SHA-256
`b3b8d04f60ef94f06c35d28713bc51ff300e65ce5214b216eda1ff3e71021eb8`;
WPS Presentation 12.1.0.26886 produced
`fa8616af0bb397108dcb03c516358fc933a45743265926dfa4ab8e26bb98dd94`.
Both producers preserved the exact radial and empty-adjustment geometry XML,
and direct review of isolated native renders found no clipping, overlap, blank
content, or semantic drift.

Write acceptance changed the radial stops to 0/45/100 percent with colors
`#FFF2CC`, `#ED7D31`, and `#7F6000`, set middle opacity to 80 percent, moved
the focus rectangle to 20/40/80/60 percent, enabled rotate-with-shape, and
changed the second shape from `roundRect` to `hexagon`. Only
`ppt/slides/slide3.xml` changed. VassilFlow output SHA-256 values were
`62bc53aafbc7bca15e122789d43f79df7790d9254eff10127d26755248f979b4`
for the PowerPoint lane and
`4bc41c9b5768de11865849fae7d00153a5d264b080881231ab8ff4197a8e6a74`
for the WPS lane. Native reopen/save produced
`01958f25d7d424589de8a8e5d98bd400104a57580a52ec4132437854248b0539`
and `fdf112b02d6ae5c33ba92f426121bf2caed10e381b1f6a104dd86b660b8d7fe7`
respectively. Every requested field survived semantic reinspection, package
validation remained clean with no risky features, and all non-target objects
remained unchanged.

PowerPoint's isolated slide-3 render was byte-identical before and after native
reopen at SHA-256
`a6543046a1f8a989a3998d3034eb27e7724dbbd8d28bae09237385e8b15ab29c`.
The corresponding WPS pair was also byte-identical at
`6bc71709361b7650037f61ee10f6f1fcd81047b9c503f3346911a3ed9cd7982d`.
Direct review confirms the requested orange radial focus and green hexagon,
with no unrelated visual change. Native COM slide export must use a fresh
output path because existing PNG files are not reliably overwritten.

Final verification passes 152 focused PPTX/corpus/tool tests, the complete
Office suite with 278 passed and one existing Starlette deprecation warning,
and all 33 tool-schema warning tests. Ruff check and format verification pass
for the changed Python surface, and the repository diff has no whitespace
errors. The backend has no configured Python type-check command. This batch
does not require runtime configuration; `config.yaml` and `.env` remain
untouched.

## Typed direct RGB pattern-fill acceptance (2026-07-15)

This batch fetched the OfficeCLI reference at commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8` and read the actual pattern and
image-fill builders in `PowerPointHandler.Fill.cs`, the shape-property dispatch
in `PowerPointHandler.ShapeProperties.cs`, and pattern/image readback in
`PowerPointHandler.NodeBuilder.cs`. The reference builds `a:pattFill` in the
required `fgClr` then `bgClr` order, but exposes a colon-delimited grammar,
implicit colors, inherited bare patterns, aliases, and broader color forms.
Its image-fill path must add binary package parts, content types, and slide
relationships; the reference also documents unresolved image-fill replay
cases. Those behaviors are not copied into VassilFlow.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Bounded pattern/image inspection, authored-ID shape paths, strict/transitional namespace handling, schema-order checks, transactional preflight, canonical preservation, and native PowerPoint/WPS harness | Reuse the existing infrastructure. |
| Port | Typed shape-only pattern fill with one bounded OOXML preset and explicit direct-RGB foreground/background colors | Open through exact authored-ID `format_pptx_shapes` targets with the required original-name guard. |
| Not suitable | String pattern grammar, aliases, inherited or defaulted colors, scheme/named colors, raw XML, silent normalization, and destructive fallback over unsupported fills | Keep these outside the VassilFlow tool boundary. |
| Defer | Image fill, pattern line fill, effects/3D, custom geometry and adjustment formulas, connector routing/endpoints, object creation, and z-order | Require separate binary/relationship or visual corpora before any write surface. |

The typed contract requires `type=pattern`, one of 54 finite OOXML preset
tokens, and explicit six-digit RGB values for both `foreground_color` and
`background_color`. It is valid only for direct authored shape fills. Shape
line and connector models reject pattern fills. Existing pattern XML is
writable only when it contains exactly one supported `prst` attribute followed
by one `fgClr` and one `bgClr`, each containing exactly one transform-free
`srgbClr`. Unknown attributes, missing colors, scheme colors, color transforms,
comments, mixed namespaces, and wrong child order fail before any target is
changed. A semantic no-op returns the exact source bytes, and the preservation
mask covers only the selected fill slot.

The deterministic corpus now has four slides and 16 objects. It adds
`VF_RT_PATTERN_FILL` at `/slide[4]/shape[@id=3]`, using `diagCross` with
foreground `#4472C4` and background `#D9EAF7`. Seed SHA-256 is
`f08f299acd61d8057df7180ad1659827b40cc4bc4b6ec3e8efc23af482c4328d`.
PowerPoint 16.0 build 20131 produced corpus fixture SHA-256
`70b24d74c49e250edeb4cdf4bf58773a275fc611d3a5a1fb7d42bbf9c4ce3850`;
WPS Presentation 12.1.0.26886 produced
`b3d6dcecebeaed7db496cd500e8d78db4fa12ae3179c7f017eba378e6c4abcce`.
Both native applications retained the exact stable path, preset, direct RGB
colors, four-slide count, and clean package validation. Baseline visual review
found no clipping, overlap, blank content, or semantic drift.

Write acceptance changed the preset to `weave`, foreground to `#C00000`, and
background to `#FFF2CC`. Only `ppt/slides/slide4.xml` changed; all shape text,
geometry, line style, and non-target objects remained byte-equivalent after
the allowed fill slot was masked. VassilFlow output SHA-256 values were
`b09c40c36930976de97a350cf2d669b913b24b5fd0313b73b8b9ed062961ccb8`
for the PowerPoint lane and
`a79dc66eb7c3eac2655ca779031855ad784b55d4db2b8e12a223a174dd53aac2`
for the WPS lane. Native reopen/save produced
`ced4e3bd39c413ab1aa4bf5f5d4943196e21e199cab1214e859acf2401873d16`
and `adf044fb0e8eefb7130c024e752594038315a16b111a6919bd8c711b5508d2da`
respectively, with exact typed semantic readback and no risky features.

PowerPoint's isolated slide-4 render was byte-identical before and after native
reopen at SHA-256
`685b968142c0875135d607fe3ab48a6d476bd448c89f945fbc129c14dae1de52`.
The corresponding WPS pair was also byte-identical at
`ec70444cd4f96b67a4b91a2a02572799153d4b2f5a9fc8768a9b29dc96cdd111`.
Direct review confirms the requested red weave over the light background with
readable text and no layout change. This batch requires no runtime
configuration; `config.yaml` and `.env` remain untouched.

Final verification passes all 125 PPTX engine tests, all 11 native corpus
tests, the complete Office stack with 287 passed and one existing Starlette
deprecation warning, and all 33 tool-schema warning tests. Ruff check and
format verification pass for the changed Python surface. The restarted
Gateway is healthy at `http://localhost:2026/`; its container schema exposes
`pattern` alongside solid, none, and gradient fill types, with all 54 bounded
pattern presets. The repository diff has no whitespace errors.

## Typed embedded PNG shape-fill acceptance (2026-07-15)

This batch read the OfficeCLI reference at commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8`, including the actual image-part
and relationship writer in `PowerPointHandler.Fill.cs`, image readback in
`PowerPointHandler.cs`, batch replay in `PptxBatchEmitter.Shape.cs`, and the
build-before-swap background path in `PowerPointHandler.Background.cs`. The
reference accepts local/remote/data-URI sources and replays shape images as
inline base64 plus raw XML for tile state. Those interfaces are not copied.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Typed read-only image framing/effects, stable authored-ID shape paths, validated OPC relationships/content types, strict/transitional namespaces, package preservation with declared additions, and the native PowerPoint/WPS harness | Reuse the existing VassilFlow infrastructure. |
| Port | Shape-only embedded PNG fill with a sandbox image path, explicit rotate-with-shape, optional four-edge crop, deterministic media/relationship creation, digest reuse, and exact no-op behavior | Open through exact `format_pptx_shapes` targets and the original-name guard. |
| Not suitable | HTTP/data-URI/base64 sources, linked images, raw XML replay, silent crop parsing, host-path access in the package writer, destructive replacement, and external relationships | Keep these outside the VassilFlow tool and engine boundary. |
| Defer | JPEG, tile/center modes, fill-rectangle tuning, alpha/effects, background/table/picture replacement, and relationship/media garbage collection | Require separate native binary and visual corpora. |

`office_edit` resolves each `image_path` under thread-scoped user data, locks it
with source and output, downloads it once, and passes only an internal byte
mapping to the PPTX engine. The writer never reads files or the network. PNG
validation precedes mutation and checks the 10 MiB file limit, 8192-pixel
dimension limit, 16-million-pixel limit, chunk order and CRC, IHDR encoding,
bounded decompression, row filters, and non-interlaced image data. A transaction
is capped at 20 MiB of image assets.

The writer adds deterministic `ppt/media/imageN.png` parts and internal slide
image relationships, adds content-type defaults or overrides only when needed,
and reuses an identical existing part/relationship by SHA-256. It never mutates
or deletes an existing media part because it may be shared. Shape XML supports
only ordered effect-free `blip`, optional `srcRect`, and `stretch/fillRect`
children. Existing linked, tiled, effect-bearing, malformed, wrong-content-type,
or wrong-relationship fills fail before any target changes. OPC preservation
declares the exact replaced and added part sets; unrelated payloads, ZIP
metadata, and existing entry order remain protected. An independent read-only
review of both source trees confirmed these boundaries and called out the same
asset-lock, relationship, content-type, no-op, and atomicity invariants.

The deterministic corpus now has five slides and 18 objects. It adds
`VF_RT_IMAGE_FILL` at `/slide[5]/shape[@id=3]`, with an embedded PNG, stretch
mode, `rotate_with_shape=false`, and crop 12.5/5/8/10 percent. Seed SHA-256 is
`03c2264f5f39a09ac1d6a0b869b2fa75615a47a40e0b95ab61a525d44f4a750f`.
PowerPoint 16.0 build 20131 produced corpus fixture SHA-256
`0efb66a4a784dca5faa7cc9a0e2a32ccf010b606c81922a089b239b12ac30903`
with 46 entries; WPS Presentation 12.1.0.26886 produced
`7649c3a042e1023b56fa56afe23b8e99f63074acbfabc5f206e1d99dcde02251`
with 59 entries. Both retain the stable target and exact framing. PowerPoint
keeps `rId2`; WPS renumbers the image to `rId1`, so the semantic contract
requires one valid internal image relationship rather than a producer-specific
ID. Direct native baseline renders passed visual review at SHA-256
`864ad5c1cf5c93aa8e6d20decaf788cf4325728ef3c714aafcbac3f214b60dd4`
and `a8b9fe4d5cd131256d607d253da7598127ba0528db84781dcfc627ecf3a545a4`.

Write acceptance embeds replacement PNG SHA-256
`af1d0d74f09b3c0d51b702bfc0425d0852b8a0bd30ab2b72b3ca4e84c1166ed2`,
sets crop to 5/12.5/15/7.5 percent, and enables rotate-with-shape. For each
native fixture, only `ppt/slides/slide5.xml` and its relationship part change,
and exactly `ppt/media/image2.png` is added. VassilFlow output SHA-256 values are
`28c4016313fe2f4c22c677ad39ef5ace8c6e14ebb7115119b0ac748e4e881bd9`
for the PowerPoint lane and
`4561c767e921a2ae20e0a2477db805ecc5458b4ccc9bcb99fe60e505a408275a`
for the WPS lane. Native reopen/save produced
`89b2b3f279f43052028537fbd648e1bd6da3d370fb186ebedd3c76fecd2f425e`
and `e87ec249d61063c2e7966f3c09aa8f84b01bb03082691e2765c2162e4ffe8608`.
Both applications garbage-collected the old unreferenced media and renamed the
replacement to `image1.png`, while exact framing and replacement bytes remained
intact. Native slide exports are byte-identical before and after reopen at
`ab50cf54390028f7b61f3cd1c53d236ab25b6003a04aa9c5c9005ab062ba9029`
and `d4f4e2a1c3cf6f0f001a4588e9c7d824d0f9f6dcd5c598776702ac408625e54c`.
Direct review confirms the purple/yellow/teal replacement, cream diagonals,
requested crop, clean rounded clipping, and no unrelated visual change.

LibreOffice renders of the WPS-authored lane expose an existing transparent
slide-background compatibility issue and do not faithfully rasterize the
diagonals. The writer/reopened LibreOffice pair is still byte-identical, but
native WPS export is the visual acceptance source for this lane. This batch
requires no runtime configuration; `config.yaml` and `.env` remain untouched.

Final verification passes all 131 PPTX engine tests, all 12 native corpus
tests, the complete Office/schema group with 335 passed and one existing
Starlette deprecation warning, and all 33 tool-schema warning tests. Ruff check
and format verification pass for the changed Python surface. The backend has
no configured Python type-check command. After the Gateway restart,
`http://localhost:2026/health` reports `vassilflow-gateway` healthy. The live
`office_edit` tool schema in that container exposes `image` in the shape-fill
type enum, the bounded `image_path`, nullable `rotate_with_shape`, and all four
required crop edges. No runtime configuration change is required.

## Baseline JPEG shape-fill and asset-inventory acceptance (2026-07-15)

This batch re-read the current OfficeCLI checkout at commit
`b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`. The directly reviewed source was
`Core/ImageSource.cs`, `Handlers/Pptx/PowerPointHandler.Fill.cs`,
`PowerPointHandler.Background.cs`, `PowerPointHandler.Set.Media.cs`, and
`PowerPointHandler.Effects.cs`. The reference recognizes JPEG by extension and
three magic bytes, accepts local files, URLs, and base64 data URIs, and lets the
Open XML SDK choose the image part type. Its picture replacement deletes the
old part before the new part is fully installed. Its background path has a
useful build-before-swap phase but later deletes old image parts, while effect
readback still has raw-XML replay paths. Those broad and destructive behaviors
are not copied.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Authored-ID shape targeting, effect-free stretch/crop image XML, sandbox asset locks, PNG validation, digest reuse, content-type/relationship planning, OPC preservation, image-fill readback, and native PowerPoint/WPS gates | Reuse the existing VassilFlow contracts. |
| Port | Package-wide incoming relationship counts, a bounded image-part inventory, definite relationship-orphan reporting, and shape-only 8-bit baseline JPEG fill | Add these without broadening selectors, sources, or framing modes. |
| Not suitable | URL/data-URI/base64 input, extension-only JPEG trust, GIF/BMP/TIFF/vector expansion, raw XML, implicit framing, delete-before-add replacement, and best-effort part deletion | Keep these outside the VassilFlow tool and writer boundary. |
| Defer | Tile/center, slide backgrounds, picture replacement, table writes, effects/3D, and media garbage collection | Require dedicated typed models, source corpora, atomic copy-on-write planning, and native visual acceptance. |

Inspection now computes incoming internal relationship counts once for the
whole package. Each resource reports its package relationship count, number of
distinct source parts, and whether multiple relationships share the target.
The top-level `image_asset_inventory` lists bounded `image/*` parts with size,
content type, relationship counts, and shared status. An `orphan` is reported
only when no internal package relationship targets that part; it is not
presented as an object-use count because one relationship ID may be referenced
by multiple XML objects. This is read-only groundwork for later copy-on-write
replacement and dry-run garbage collection.

The JPEG writer accepts only `.jpg` or `.jpeg` sandbox paths whose bytes form a
single-scan SOF0 JPEG with 8-bit samples, one grayscale or three color
components, bounded dimensions, valid quantization and Huffman tables, and a
complete entropy stream. Progressive, arithmetic-coded, CMYK/YCCK,
EXIF-bearing, multi-scan, truncated, malformed, or suffix-mismatched input
fails before package mutation. PNG and JPEG deduplication keys include both
content type and SHA-256. New media numbering is global across existing
`imageN.*` names, and JPEG additions use `image/jpeg` plus canonical `.jpg`
parts. Existing parts and relationships are never deleted by this writer.

The deterministic corpus now has six slides and 20 objects. It adds
`VF_RT_JPEG_FILL` at `/slide[6]/shape[@id=3]`, backed by a 640x360 baseline RGB
JPEG with stretch mode, `rotate_with_shape=true`, and crop 6/9/14/4 percent.
Seed SHA-256 is
`8b8f48b2856ba618cbbfc9dcf20ccb89b4cdded2746e0303eb6a312d1f501e68`.
PowerPoint 16.0 build 20131 produced
`80abd4181dbe370d42829a916f530530fc501f3f4033234b702d6456023243e2`
with 49 entries; WPS Presentation 12.1.0.26886 produced
`98f108be8e2946fc4d2f176e9a00a36e49e2c683fcb5a89e642ad40e612b572e`
with 62 entries. Both preserve the target, crop, framing, and exact JPEG bytes.
Native baseline slide renders have SHA-256 values
`2d57b3adcaa09dd54088b1635547e3579b3ba16b2167eea27825e1d2e581814b`
and `e905cbd8977df094e11a6f18b998382e5ce17fa51b44609cc43af63c59e80fd8`;
direct review found no clipping, overlap, blank output, or aspect-ratio drift.

Write acceptance embeds replacement JPEG SHA-256
`a3d072163511bdfa7cab283d90cfccdbd235f656db726c4a841d1bc427e0cb2d`,
sets crop to 8/6/4/11 percent, and disables rotate-with-shape. VassilFlow output
SHA-256 values are
`39c6f8e40e13c7ee4b69cdf0997279ac54174d78eb70c483d1dcfa3a392abf57`
for the PowerPoint lane and
`179dbe8d29fed9b3a9831efaf73226860f3c4c5363aa4689748b61f5dc8aae5a`
for the WPS lane. Native reopen/save produced
`8745fa4eb71bdc78eb1fad9fedffc4a25fd748d485f5d940549164a746ee5d72`
and `86e72b53ea249d8c18143f7526e060bad52a014f4244d66cbd2371d4627ee728`.
Both applications compacted the unused prior relationship/media part and
renumbered the replacement, but the requested typed semantics and JPEG bytes
remained exact; every non-target object was unchanged. Final native slide
renders have SHA-256 values
`d2656823325a5f5ff00205a37419c5556b9051e404809cf46b7652f5833f7c6d`
and `3342faabbca8b99b3863b0ceb7881d1eb8f5ab293944c9f76d09e18d1dabb9b4`.
Direct review confirms the purple/blue/green replacement, cream diagonals,
requested crop, and clean rounded clipping in both applications.

This batch requires no runtime configuration; `config.yaml` and `.env` remain
untouched. Tile/center, background, picture/table replacement, effects/3D, and
garbage-collection writes remain closed.

Final verification passes all 142 PPTX engine tests, all 13 native corpus
tests, and the complete Office plus tool-schema group with 350 passed and one
existing Starlette deprecation warning. Ruff check and format verification
pass for the 17 inspected Office/script/test Python files, and the repository
diff has no whitespace errors. The backend has no configured Python type-check
command. After restarting the bind-mounted Gateway,
`http://localhost:2026/health` reports `vassilflow-gateway` healthy. The live
`office_edit` tool-call schema describes PNG or baseline JPEG input, and the
container policy accepts both `.jpg` and `.jpeg` thread paths.

## Typed tile and centered shape-image framing acceptance (2026-07-15)

This batch re-read the OfficeCLI checkout at commit
`b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`, specifically
`PowerPointHandler.Fill.cs`, `PowerPointHandler.Background.cs`,
`PowerPointHandler.Add.Media.cs`, `PowerPointHandler.NodeBuilder.cs`,
`PptxBatchEmitter.Shape.cs`, `ImageSource.cs`, and
`PowerPointHandler.Set.Media.cs`. The reference confirms DrawingML child order
and represents centered framing as a 100-percent tile aligned to `ctr`. Its
broad string parsers, silent defaults, URL/data-URI sources, and raw XML replay
remain outside the VassilFlow boundary.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Authored-ID shape selectors, Strict/Transitional namespace handling, bounded PNG/JPEG validation, digest-based asset reuse, transactional relationship/content-type planning, image-fill inspection, and native producer harnesses | Reuse these contracts. |
| Port | Shape-only `stretch`, explicit `tile`, and canonical `center` framing; ordered `blip[,srcRect],tile|stretch`; typed scale, offset, alignment, and flip | Open only after native corpus and visual acceptance. |
| Not suitable | Raw tile strings/XML, implicit defaults, URL/base64 input, silent parse fallback, destructive media replacement, and broad image-format expansion | Keep rejected at model, asset-policy, or writer preflight. |
| Defer | Crop combined with tile/center, `fillRect` tuning, slide backgrounds, picture/table replacement, effects/3D, and media garbage collection | Require separate corpora and copy-on-write designs. |

`PptxShapeFillFormatting.mode` now accepts `stretch`, `tile`, or `center`.
Omitting it preserves the existing stretch contract. Tile mode requires all six
typed fields: signed `offset_x_emu` and `offset_y_emu`, 1-500 percent X/Y scale
at 0.001-percent precision, one of nine rectangle alignments, and one of four
flip modes. Center mode emits the corpus-verified canonical tile at 100 percent
with center alignment and no offsets. Crop remains stretch-only. Unsupported,
missing, reordered, linked, effect-bearing, or out-of-range tile metadata fails
before any package mutation.

The deterministic corpus now has seven slides and 23 objects. Slide 7 adds
`VF_RT_IMAGE_TILE` with `tx=127000`, `ty=-63500`, `sx=45000`, `sy=65000`,
`algn=br`, and `flip=x`, plus `VF_RT_IMAGE_CENTER` with 100-percent center
framing. Seed SHA-256 is
`2ef2d18ec1d399410143d23e4f33b2c0cd64048bc4de31a42720e99e4c5c600e`.
PowerPoint 16.0 build 20131 produced fixture SHA-256
`6881841f441089b0c59ad3e3e66164c452ccb242d030afe4825daa3464defe6c`
with 53 entries; WPS Presentation 12.1.0.26886 produced
`3cd6e66110e44a35c1bacf7a658404f751c97625d6a802d61b0edda85ec4817e`
with 66 entries. Both retain every tile value exactly; WPS only renumbers the
relationship IDs. Native 1600x900 exports passed direct visual review with
clean rounded clipping, visible repetition/flip for tile, and stable centered
framing.

Writer acceptance changed the tile to offsets -254000/190500, scale
72.5/38.25 percent, top-left alignment, both-axis flip, and changed the center
shape's rotate-with-shape flag. For both native fixtures the transaction reused
the existing image parts and relationships, added or deleted no package entry,
and changed only `ppt/slides/slide7.xml`. Repeating the same operation returned
the exact input bytes. PowerPoint and WPS reopened and saved the writer output
while preserving every requested value and reporting no risky feature. Final
native slide-render SHA-256 values are
`8559053683f89075cbb928ef558f5a66799e244888dfd40373fd81612862ef9b`
and `529505fbac9f3871202feb486e790cd49c1d7ac155fe861f3781e353555f2e09`;
direct review found matching framing with no blank media, overlap, or clipping
regression.

This batch changes no runtime setting. `config.yaml` and `.env` remain
untouched. Background, picture/table replacement, effects/3D, and media
garbage-collection writes remain closed.

Final verification passes the complete Office and tool-schema group with 365
tests and one existing Starlette deprecation warning, including all 14 native
corpus tests. Ruff check and format verification pass for the 16 inspected
Office/script/test Python files, and the repository diff has no whitespace
errors. The backend has no configured Python type-check command. The
bind-mounted Gateway reloaded cleanly; `http://localhost:2026/health` reports
`vassilflow-gateway` healthy, and its live `office_edit` schema exposes all
three modes plus the six required tile fields.

## Typed direct slide-background acceptance (2026-07-15)

This batch re-read the OfficeCLI checkout at commit
`b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`, specifically
`PowerPointHandler.Background.cs` and
`PowerPointHandler.Set.Slide.cs`, then compared them directly with VassilFlow's
`models.py`, `pptx.py`, Office tool boundary, native corpus builder, and tests.
The reference's build-before-swap and relationship-preserving image mutation
are useful. Its raw string grammar, slide-layout/master mutation, broad image
source resolver, alpha effects, implicit defaults, and destructive old-image
part deletion do not fit VassilFlow's bounded transaction model.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Slide-order paths and `part_name`, direct background readback including `bgRef`, typed fill/image inspection, Strict/Transitional namespaces, bounded PNG/JPEG validation, digest reuse, transactional relationship/content-type planning, and native producer harnesses | Reuse these contracts. |
| Port | Direct slide-only `none`, RGB solid, bounded RGB linear gradient, and embedded PNG/baseline-JPEG background writes; exact `/slide[N]` targets with required original `part_name`; stretch, explicit tile, and 100-percent center-aligned framing | Open only after native corpus, reopen, and rendered acceptance. |
| Not suitable | Raw background strings, URL/data-URI/base64 input, layout/master mutation, pattern fallback, implicit parse defaults, alpha/effect mutation, broad image formats, and deleting the prior relationship/media part | Keep rejected by model or preflight; preserve old media for later explicit garbage collection. |
| Defer | `bgRef` writes, shade-to-title, path/radial backgrounds, no-repeat/fit/cover semantics, crop/fill-rectangle tuning, authored effects/3D, layout/master backgrounds, picture/table replacement, and media garbage collection | Require separate typed models and native visual corpora. |

`format_pptx_slide_backgrounds` now accepts only an exact slide selector. Each
target carries the inspection path plus required `expected_part_name`; this
rejects a stale positional path after slide reordering. The formatting model
contains only `none`, `solid`, `gradient`, or `image`. It intentionally has no
raw XML, pattern, rotate-with-shape, crop, alpha, effect, theme-reference,
layout, or master field. Existing `bgRef`, shade-to-title, radial/path gradient,
non-empty effect list, linked image, malformed framing, or mixed namespace
fails before mutation. A producer-authored empty `a:effectLst` is accepted as
default noise and preserved by semantic no-op detection.

Image backgrounds use the existing copy-on-write image planner rather than a
second media implementation. The planner validates all assets before touching
slide XML, reuses byte-identical image parts and relationships, allocates new
parts only when needed, and never deletes the old relationship or media. The
background is built completely before replacing `<p:bg>` and is inserted
before `<p:spTree>`. The preservation invariant masks only that one background
slot; object text, geometry, animation, interactions, slide metadata, and all
other package parts must remain byte-stable.

The deterministic corpus now has 12 slides and 28 objects. Slides 8-12 add a
direct RGB solid, three-stop linear gradient, stretched baseline JPEG, explicit
PNG tile, and 100-percent center-aligned PNG background. Seed SHA-256 is
`8041fc6b4a1905ea327086a67e71a085255593c74986c6eb16a47a2241be72d5`.
PowerPoint 16.0 build 20131 produced fixture SHA-256
`9b613569498603d92bb75f79871e6b3551ba8726f69268a1b5a03ab030ea4bce`
with 66 entries; WPS Presentation 12.1.0.26886 produced fixture SHA-256
`981c3d13d8bac698a1b2d1d9e1be0f32f8d1af5b87a8747982205e32e07d2b64`
with 79 entries. Both preserve the fill kind, gradient stops/angle/scaling,
stretch rectangle, every explicit tile field, and center framing. Native apps
drop the authored false `shadeToTitle` default and WPS renumbers relationships;
the semantic contract correctly ignores those physical normalizations.

Writer acceptance changed slides 8-12 to a new solid, a new three-stop linear
gradient, a replacement JPEG stretch, replacement PNG tile, and replacement
PNG center. The two image payloads produced only two new media parts; tile and
center share the same PNG while each slide owns its relationship. Repeating
the complete transaction returned the exact edited bytes. PowerPoint reopened
output SHA-256
`42c10ff6ccc5bc899f26a707d3235e3bffee6094cf1a8ec3a5d64da8b03fdc54`;
WPS reopened output SHA-256
`1b685efb41dca16edccb273365dfd7d1e70b9f028330a6c2140a5120d627fc62`.
Both retained all requested typed values and all 28 objects.

Native 1600x900 exports from both reopened outputs match for solid, gradient,
stretch, tile, and center alignment with no blank frame, broken media, title
overlap, or clipping regression. The small 640x360 center asset visibly repeats
on a 1600x900 slide. This confirms the actual OOXML behavior: the accepted
center representation is a 100-percent tile anchored at `ctr`, not a no-repeat
primitive. VassilFlow documents that behavior and does not copy the reference
source's no-repeat claim. A true no-repeat/fit/cover surface remains deferred.

This batch changes no runtime setting. `config.yaml` and `.env` remain
untouched. Picture/table replacement, effects/3D, inherited/theme/layout/master
background writes, and media garbage collection remain closed.

Final verification passes the complete Office and tool-schema group with 364
tests and one existing Starlette/httpx deprecation warning. Ruff check and
format verification pass for the seven changed Office/script/test Python
files, and `git diff --check` reports no whitespace errors. The running Docker
Gateway reports healthy at `http://localhost:2026/health`; importing the live
bind-mounted `office_edit` schema inside that container exposes
`format_pptx_slide_backgrounds`, all four background types, the
stretch/tile/center image modes, and the required `path` plus
`expected_part_name` target fields.

## Typed source-only picture replacement acceptance (2026-07-15)

This batch updated the research checkout and read the actual OfficeCLI
`origin/main` implementation at commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8`, specifically
`PowerPointHandler.Set.Media.cs` and `schemas/help/pptx/picture.json`. The
relevant implementation is unchanged from the local shallow checkout at
`b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`. The useful primitive is changing
only `a:blip/@r:embed`, including pictures inside groups. Its positional
selectors, property bags, URL/data-URI/raw-byte sources, automatic alt-text
mutation, broad image formats, and destructive `DeletePart` path do not fit
VassilFlow's transaction and preservation contracts.

An independent code review compared both implementations and confirmed a key
architecture boundary: picture replacement must not pass through the shape
image-fill signature or builder. That path intentionally rejects rich picture
blips and would conflate source replacement with crop, effects, and framing
mutation.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Stable authored-ID object/group paths, picture formatting readback, relationship ownership, bounded PNG/baseline-JPEG validation, content-type plus SHA-256 deduplication, copy-on-write media planning, transaction rollback, and OPC preservation | Reuse these contracts and expose the existing source ownership more precisely. |
| Port | Source-only replacement for native `p:pic`; exact path plus original name and source SHA-256 guards; change only the embedded relationship; preserve every other picture and slide property | Open after native corpus, reopen, and rendered acceptance. |
| Not suitable | Positional selectors, generic property bags, URL/base64/raw-byte input, silent aliases/defaults, automatic alt-text changes, SVG/GIF expansion, linked sources, and deleting old relationships or parts | Reject at the typed model, package preflight, or asset validator. |
| Defer | Picture add/remove, crop/framing/effect/geometry writes, SVG dual representation, video posters, table-cell images, and media garbage collection | Require separate typed models, producer corpora, and visual acceptance. |

`replace_pptx_picture_sources` contains only `type`, `pictures`, and
`image_path`. Each target is an exact authored-ID picture path with required
`expected_name` and lowercase `expected_source_sha256`. Inspection now returns
the source relationship ID, resolved part name, content type, byte size, and
SHA-256 on each safely bound picture. Resource and package-wide image records
also include the digest.

Preflight requires one native picture, one direct `p:blipFill`, one direct
`a:blip`, one internal embedded image relationship, one supported existing PNG
or baseline-JPEG part, and one consistent Strict or Transitional namespace
family. Linked sources, companion SVG relationships, multiple blips,
video/audio identity, mixed namespaces, stale names, and stale source hashes
fail before the first mutation. The writer changes only `a:blip/@r:embed`.
Its preservation gate masks exactly that attribute; crop, fill rectangle, DPI,
compression state, direct effects, transform, geometry, placeholder data, alt
text, interactions, z-order, and animation identity must remain canonical-byte
equivalent. Existing relationships and media are retained for a later explicit
garbage-collection operation.

The deterministic corpus now has 13 slides and 32 objects. Slide 13 adds
`VF_RT_PICTURE_EFFECT`, `VF_RT_PICTURE_SHARED`, and `VF_RT_PICTURE_JPEG`.
The first two share PNG SHA-256
`e44121807d48ae90a4f8d29b6130609bfcdc24ddaa1fd9014a91deecd5a86e83`;
the third owns baseline JPEG SHA-256
`7cc3e2ac4d6ed2d7efcf4d07fbc3a66d8362ae16597edb1df8b223e5a2f0d167`.
The effect picture covers crop, non-empty fill rectangle, authored DPI,
compression state, alpha/luminance values, and stretch framing. Its peer covers
shared ownership, rotate-with-shape, and grayscale.

An initial native experiment also authored tile and center framing directly on
`p:pic`. PowerPoint rendered repeated tile/center behavior, while WPS preserved
the attributes but rendered one stretched image. The acceptance corpus was
therefore narrowed to producer-consistent stretch pictures; tile/center picture
writes remain closed instead of inheriting the shape-fill contract by analogy.

Seed SHA-256 is
`5b0947cb1e6a7aceb4860835d67a341184f1d8336ec731ae3f9b482f2c2607e6`.
PowerPoint 16.0 build 20131 produced fixture SHA-256
`af2e6fa974d270063e3e58a955bda01edb62be184b5b1740b449c92113a27377`
with 70 entries; WPS Presentation 12.1.0.26886 produced fixture SHA-256
`b843fa231e15809d45623ec5f74276d76f3969afac743d75378951e675e5ca62`
with 83 entries. Both preserve all three authored pictures and shared-source
semantics. WPS drops the optional authored DPI default, renumbers
relationships, and canonicalizes `.jpg` to `.jpeg`; the manifest excludes
those producer-unstable physical details.

Writer acceptance replaced the effect picture with JPEG SHA-256
`a3d072163511bdfa7cab283d90cfccdbd235f656db726c4a841d1bc427e0cb2d`
and the baseline-JPEG picture with PNG SHA-256
`af1d0d74f09b3c0d51b702bfc0425d0852b8a0bd30ab2b72b3ca4e84c1166ed2`.
VassilFlow output SHA-256 values are
`57f1fec666ab210ef85681e0299544595f6c5baea0a8c33ac8391bfe74ccc490`
for the PowerPoint lane and
`4d9aedd00b66c41871a509415123acf3e3cf31a106a544ca1776e7deb8cb231e`
for the WPS lane. Both transactions add two media parts, alter only the slide
13 relationship part plus slide XML, preserve the shared peer, and return exact
input bytes for a same-content operation with a refreshed guard.

PowerPoint native reopen/save produced SHA-256
`0a5004cba38055d2e863270986b04ccc53cd42206d67c87c20ca84f66699c4c4`
with 71 entries; WPS produced
`5412e786767c5da3e5acac702569549a29be7fef5a586a3f43347ba39742afa5`
with 84 entries. Both applications compacted unused media, renamed or
renumbered the three slide-13 picture relationships, and retained 11 image
parts. The two requested source digests, the shared source digest, all 32 object
identities, and every non-source picture property remained semantically exact;
no non-target object changed.

Native 1600x900 slide-13 exports have SHA-256 values
`ba05f8982382306f056e284e797cdef1fcb737b447d4d8642ef223a48bc0cc65`
for PowerPoint and
`5ba4863bfade9ff02eb4b52107cbb3995547005b6ad18ffd0a9c4db226f82586`
for WPS. Direct visual review confirms matching crop and stretch framing, the
preserved alpha/luminance treatment on the replaced effect picture, unchanged
grayscale on the shared peer, and the vivid PNG replacement on the third
picture. Neither render has blank media, overlap, clipping, or aspect-ratio
regression.

This batch changes no runtime setting. `config.yaml` and `.env` remain
untouched. Picture add/remove, picture crop/framing/effect/geometry mutation,
SVG/GIF/video support, table or table-cell picture replacement, effects/3D,
and media garbage collection remain closed.

Final verification passes all 163 PPTX engine tests, all 16 native corpus
tests, and the complete Office plus tool-schema group with 376 passed and one
existing Starlette/httpx deprecation warning. Ruff check and format
verification pass for the seven changed Office/script/test Python files, and
`git diff --check` reports no whitespace errors. The running Docker Gateway is
healthy at `http://localhost:2026/health`; its live bind-mounted
`office_edit` schema exposes `PptxPictureSourceReplacementOperation`,
`PptxPictureSelector`, the three required target guard fields, and only
`type`, `pictures`, plus `image_path` on the operation.

## Read-only PPTX media cleanup evidence (2026-07-15)

This batch read the actual research checkout at OfficeCLI `origin/main` commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8` and compared it with the local
checkout at `b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`. The deletion paths reviewed
directly were `PowerPointHandler.Set.Media.cs`,
`PowerPointHandler.Background.cs`, `PowerPointHandler.Resolve.cs`, and
`PowerPointHandler.Mutations.cs`. The useful idea is relationship-aware media
reference counting. The source implementation's immediate `DeletePart` calls,
best-effort exception swallowing, same-slide top-level-picture count, and raw
`OuterXml` substring checks are not safe enough for VassilFlow's package-wide
preservation boundary.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Raw-ZIP part inventory, content types, package-wide internal relationship graph, image byte sizes and SHA-256 values, Strict/Transitional namespaces, bounded secure XML parsing, and copy-on-write image writes | Reuse these primitives without adding another package model. |
| Port | Source-part-scoped relationship-reference counting and media evidence reporting | Expose only as opt-in, bounded, non-destructive inspection. |
| Not suitable | Immediate part deletion, swallowed cleanup failures, direct-picture-only counting, positional object queries, and raw XML substring liveness checks | Keep outside models and writers. |
| Defer | Relationship or part deletion, package-root reachability collection, direct part-URI discovery, binary/custom owners, out-of-scope images, SVG dual-representation cleanup, video/audio data parts, and table-picture cleanup | Require a separate executor contract and broader producer corpus. |

`office_inspect(include_pptx_media_gc_plan=true)` now returns contract version
1 evidence for content-type `image/*` parts under `ppt/media`. The analysis is
package-wide and independent of `start_slide`, `max_slides`, and
`pptx_selector`. It counts exact relationship-namespace attributes within each
relationship's own XML source part. Relationships with at least one reference
remain protected. Zero-reference standard image relationships and image parts
with zero incoming relationships are reported as evidence records. A target
part is not reported when another relationship or source remains live.

The response is intentionally non-actionable: `actionable`, `destructive`, and
`deletion_supported` are false, and `candidate_evidence_only` is true. It binds
the plan to `package_sha256` and binds relationship evidence to target,
source-part, and relationship-part hashes. Status values describe only the
observed evidence, such as `zero_incoming_relationships` and
`all_incoming_relationships_have_zero_xml_references`.
`estimated_reclaimable_uncompressed_bytes` is the sum of ZIP uncompressed part
sizes in evidence records, not deletion authorization. Images outside
`ppt/media`, including package thumbnails, are returned as bounded protected
records.

The reviewer identified a concrete false-positive risk in the first draft: a
binary owner containing parseable XML could be treated as an XML source. The
final planner requires a declared `application/xml`, `text/xml`, or `+xml`
content type and rejects relationship-part owners. Missing sources, parseable
non-XML content, malformed XML, nonstandard relationship types, per-source
limits, total XML budget exhaustion, and the relationship cap produce explicit
blockers. Any blocker makes `analysis_complete` false. Candidate arrays may
still contain independent evidence, but all records remain non-actionable and
no executor exists.

The contract explicitly lists its remaining limits: package-root reachability,
direct part-URI references, and undeclared relationship references outside the
scanned source parts are not analyzed. These limits are why destructive media
cleanup remains deferred even when the dry-run is otherwise complete.

Synthetic tests cover opt-in behavior, protected package thumbnails, exact
hash binding, zero-incoming parts, stale source-only replacement relationships,
shared rIds, multiple sources, two different rIds targeting one part,
background/group/SVG companion references, Strict references owned by slide
masters, layouts, notes, and themes, parseable binary owners, nonstandard
relationship types, relationship and XML-scan limits, and bounded output.
Both verified native producer fixtures have nine live image relationships and
zero evidence candidates at baseline. After source-only picture replacement,
both lanes report only the exclusive old JPEG relationship/part; the shared PNG
remains live.

No Office bytes are mutated by this feature, so a new native reopen or visual
render would not add evidence beyond the existing hash-bound PowerPoint/WPS
fixtures. The corpus is nevertheless executed on both native files. This batch
changes no runtime setting; `config.yaml`, `.env`, and `frontend/.env` remain
untouched. Destructive media cleanup stays closed.

Final verification passes all 174 PPTX engine tests, all 17 native corpus
tests, and the complete Office plus tool-schema group with 389 passed and one
existing Starlette/httpx deprecation warning. Ruff check and format
verification cover the changed Office and test Python files. The running
Gateway remains healthy at `http://localhost:2026/health`, and its live
bind-mounted `office_inspect` schema exposes
`include_pptx_media_gc_plan` as a non-destructive, non-actionable dry-run.

## Package-root and declared-XML integrity evidence (2026-07-15)

This follow-up re-read the actual OfficeCLI research checkout at local commit
`b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6` against `origin/main` commit
`4ba79f0b984e141f57f58d4398ba2df29e8187e8`. The comparison covered
`PowerPointHandler.cs::EnumeratePartUris`,
`PowerPointHandler.View.cs::ViewAsIssues`,
`PowerPointHandler.cs::GetPictureBlipCompanionParts`, and
`PowerPointHandler.Resolve.cs::RemovePictureWithCleanup`. The source combines
an SDK-reachable graph with raw ZIP enumeration, but its issue scan is
slide-scoped and its cleanup path can immediately call `DeletePart` after
same-slide top-level-picture checks. VassilFlow uses only the graph and
integrity concepts; it does not import the SDK authority, best-effort catch
behavior, or deletion path.

| Classification | Scope | Decision |
| --- | --- | --- |
| Already present | Raw ZIP inventory, all relationship parts, internal target validation, Strict and Transitional relationship namespaces, secure bounded XML parsing, content types, and image hashes | Extend the existing package model rather than introduce a second graph. |
| Port | Package-root reachability, package-wide declared-XML `r:id`/`r:embed`/`r:link` integrity, projected reachability after proven zero-reference standard image edges, and bounded evidence for root-unreachable image islands | Implement as media-plan contract version 2, still read-only and non-actionable. |
| Not suitable | Open XML SDK reachability as sole authority, swallowed best-effort failures, slide-only or top-level-picture-only reference scans, and immediate `DeletePart` cleanup | Keep outside the VassilFlow runtime and writer surface. |
| Defer | Relationship or part deletion, broad direct-part-URI heuristics, audio/video data-part cleanup, and unreachable package-island removal | Require a separate executor design and producer corpus; no write surface is opened here. |

Contract version 2 builds a cycle-safe internal relationship graph from the
package root before candidate analysis. It then scans every part whose declared
content type is `application/xml`, `text/xml`, or `+xml`, under per-part and
package-wide budgets. Only the standard relationship-reference attributes
`r:id`, `r:embed`, and `r:link` are counted; arbitrary attributes such as
`r:label` are not treated as relationship IDs. Undeclared counted references
produce hash-bound package-integrity blockers. A second graph pass excludes
only standard image relationships proven to have zero references in their own
source XML. Package-root image relationships remain implicit live edges.

Root-unreachable `ppt/media` image parts now have a separate bounded evidence
view. Each record includes the target hash, before/after reachability, aggregate
incoming state, and bounded incoming relationship records with owner-part,
relationship-part, and available source hashes. These records use
`reason: unreachable_from_package_root` and `actionable: false`; they are not
part candidates and do not authorize island removal. Direct part-URI
references, non-XML or untyped contents, and non-image relationship semantics
remain explicit limitations.

An independent code review found two package-integrity gaps below the planner.
A non-root `.rels` part could previously exist without its source owner, and an
unknown or empty `TargetMode` was silently coerced to an internal relationship.
The common package loader now rejects every ownerless relationship part and
accepts only an omitted `TargetMode` or explicit `Internal`/`External` value.
These checks apply before graph construction and protect every PPTX operation,
not only media inspection.

Synthetic coverage now includes missing relationship owners, invalid and empty
`TargetMode`, ignored non-reference relationship-namespace attributes,
undeclared references in non-slide XML, package-root image edges,
root-unreachable live owner islands with exact hash/state evidence, explicit
ZIP directory entries, cyclic graphs with multiple package-root paths, output
bounds, relationship caps, and XML budgets. The verified PowerPoint and WPS
fixtures still pass all 17 native corpus tests: nine scoped images are
root-reachable at baseline, and source-only replacement makes only the
exclusive old JPEG unreachable after zero-reference image edges are filtered.

No Office bytes, runtime settings, `config.yaml`, `.env`, or `frontend/.env`
are changed by this batch. The PPTX engine passes 184 tests. The complete
Office group passes 366 tests and its model-facing tool-schema companion passes
33 tests, for 399 passed in the reported group, with one existing
Starlette/httpx deprecation warning. Ruff format and lint checks pass for the
changed Office and test Python files. The running Gateway is healthy at
`http://localhost:2026/health`. Its live tool-facing schema contains the new
root-unreachable evidence description, and live inspection of the verified
PowerPoint fixture returns contract version 2, complete declared-XML integrity,
nine root-reachable scoped images, zero root-unreachable evidence records, and
`deletion_supported: false`.

## Stable Office checkpoint verification (2026-07-16)

The complete Office checkpoint includes the structured engine, isolated
renderer and fixed-route proxy, sandbox atomic replacement contract,
hash-bound visual-review state, presentation gate, configuration migration,
native PowerPoint/WPS corpus, public documentation, attribution, and internal
audit trail. Local `config.yaml`, `.env`, `frontend/.env`, research checkouts,
and runtime caches are excluded.

The changed-surface gate passes 593 tests with one environment-dependent skip.
The full backend suite passes 6,010 tests with 38 skips after deselecting nine
symlink tests that Windows cannot set up without the symlink privilege
(`WinError 1314`); the same run has no remaining functional failure. The replay
golden was regenerated through its documented writer after
`visual_reviewed_images` became a deliberate streamed state key, then passed
again without replay misses. Ruff check and format verification pass over all
42 checkpoint Python files. The backend lockfile and both Docker Compose files
validate successfully.

Live smoke verification reports a healthy Gateway and Office renderer. The
tool-facing schema exposes `include_pptx_media_gc_plan`; the verified
PowerPoint fixture returns cleanup contract version 2 with complete analysis,
nine root-reachable scoped images, and `deletion_supported: false`. The three
native fixture hashes match their manifest and producer receipts.

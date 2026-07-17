# VassilFlow Office Capability Research Audit

Date: 2026-07-16

## Scope

This audit evaluates HyCanvas as a read-only engineering reference for the next
VassilFlow Office roadmap. It compares actual source behavior with the current
VassilFlow Office engine; it does not propose embedding the application or
replacing VassilFlow's OOXML-preserving architecture.

Reference source:

- Repository: https://github.com/hyscaler/HyCanvas
- Branch: `development`
- Audited checkout: `e11c294c2797939ec2a1b84298b020f995b4a1d2`
- License: Elastic License 2.0

## License And Identity Boundary

The reference repository is not under a permissive license compatible with a
routine source port. Its license also places restrictions on offering a
substantial set of its functionality as a hosted or managed service.

For VassilFlow, the boundary is therefore strict:

- Do not copy source, schemas, tests, comments, user-facing copy, package names,
  or identity-bearing assets from the reference repository.
- Use the source only to discover product requirements, failure modes, and
  useful architectural boundaries.
- Write VassilFlow-owned specifications and tests before implementation.
- Keep all production naming, wire formats, docs, UI, and configuration native
  to VassilFlow.
- Do not add a runtime or build-time dependency on the reference repository.

This document is an internal traceability record. No reference identity should
appear in public VassilFlow product surfaces as a result of this research.

## Source Read

The audit read implementation rather than relying on repository descriptions.
The principal paths inspected were:

- `LICENSE`, `NOTICE`, and root workspace metadata
- `packages/schema/src/schema.ts`
- `packages/schema/src/validate.ts`
- `packages/schema/src/unknown-nodes.ts`
- `packages/schema/src/visitor.ts`
- `packages/schema/src/migrate.ts`
- `packages/schema/src/theme.ts`
- `packages/schema/src/a11y.ts`
- `packages/geometry/src/connector.ts`
- `packages/editor/src/history.ts`
- `packages/editor/src/commands.ts`
- `packages/editor/src/arrange.ts`
- `packages/editor/src/snapping.ts`
- `packages/editor/src/resize.ts`
- `packages/editor/src/selection.ts`
- `packages/text/src/layout.ts`
- `packages/text/src/autofit.ts`
- `packages/text/src/cascade.ts`
- `packages/text/src/fonts.ts`
- `packages/engine/src/scene.ts`
- `packages/engine/src/spatial.ts`
- `packages/engine/src/deck.ts`
- `packages/engine/src/effects.ts`
- `packages/engine/src/renderer.ts`
- `packages/engine/src/render2d.ts`
- `packages/export/src/preflight.ts`
- `packages/export/src/types.ts`
- `packages/export/src/svg.ts`
- `packages/aistudio/src/spec.ts`
- `packages/aistudio/src/layout.ts`
- `packages/aistudio/src/quality.ts`
- `packages/aistudio/src/outline.ts`
- `packages/aistudio/src/deck.ts`
- `packages/docs/src/model.ts`
- `packages/docs/src/diff.ts`
- `packages/docs/src/convert.ts`
- `packages/sheets/src/model.ts`
- `frontend/src/lib/assist.ts`
- `backend/internal/docexport/docx.go`
- `docs/roadmap/28-presentations.md`

The corresponding schema, geometry, text, engine, editor, export, accessibility,
document, sheet, formula, and generation tests were also inspected. They were
used as evidence of intended behavior, not copied into VassilFlow.

## What The Reference Actually Provides

The strongest part of the reference is an editable design model above any
specific Office format:

- A versioned scene schema with stable node IDs, pages, transforms, text runs,
  fills, strokes, effects, constraints, themes, layouts, and placeholders.
- Deterministic editor operations for history, grouping, arranging, snapping,
  and bounded geometry changes.
- A semantic generation contract in which a model produces content roles and
  layout intent while deterministic code chooses coordinates.
- Read-only design checks for fit, overlap, contrast, off-canvas elements,
  readability, style consistency, low image resolution, and accessibility.
- A browser-oriented Canvas/SVG rendering and editing stack.

The reference is not a mature Office interoperability engine:

- Its presentation roadmap explicitly records PPTX import/export as not
  started, and no PresentationML implementation was found in source.
- Its DOCX exporter builds a small document package and degrades several rich
  objects to placeholders; it is not a preservation-oriented DOCX editor.
- Its sheet and formula layers are independent simplified models, not an XLSX
  calculation or compatibility authority.
- Canvas rendering intentionally approximates several text/effect behaviors.
  True shaping, full bidirectional text, some effects, GPU rendering, and real
  3D remain incomplete or deferred.
- Connector routing has straight, elbow, and curved modes but no obstacle
  avoidance.
- Some quality checks are deliberately heuristic. For example, contrast may be
  measured against a page color or a containing solid shape rather than a fully
  composited background, and generic overlap checks cannot distinguish intended
  layering from a defect.

## Direct Comparison

VassilFlow is already stronger at actual Office package work:

- Bounded OPC/ZIP/XML validation and active-content policy
- Exact selectors and stale-state guards bound to inspected source
- Save-once typed transactions with no-op package preservation
- Existing DOCX, XLSX, and PPTX inspection and typed formatting surfaces
- PPTX object paths, geometry, z-order, alt text, source relationships, notes,
  comments, transitions, animations, fills, and effect inspection
- Isolated native rendering with source and artifact hashes
- A visual-review gate that does not equate successful rendering with review
- PowerPoint/WPS round-trip corpus work around the opened write surfaces

The reference is stronger in the layer before Office serialization:

- Semantic outline and content roles
- Versioned design intent independent of raw OOXML coordinates
- Deterministic layout and fit logic
- Arrange, snap, distribute, and tidy operations
- Design-quality and export-preflight issue reporting
- Reversible command history for an interactive authoring surface

The correct integration direction is therefore additive: build a VassilFlow
generation and quality layer above the current Office engine, then compile to
editable OOXML and validate with the existing native render/review pipeline.
The generic scene model should not replace package-preserving Office edits.

## Classification

### Already In VassilFlow

| Capability                 | Evidence in VassilFlow                                                                           | Decision                                           |
| -------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| Typed exact selectors      | DOCX/XLSX/PPTX operation models and inspected object paths                                       | Keep current contracts                             |
| Stale-source protection    | Source hashes and expected-value guards                                                          | Keep mandatory for mutations                       |
| Package preservation       | OPC-aware bounded transactions and no-op byte preservation                                       | Keep as the Office foundation                      |
| Native visual QA           | Isolated renderer, bounded page windows, artifact validation, explicit page review               | Keep as final fidelity authority                   |
| PPTX structural inspection | Shapes, text, geometry, z-order, media, notes, comments, transitions, animations, fills, effects | Extend incrementally                               |
| Rich typed formatting      | Text, run, paragraph, shape, line, fill, background, and picture source surfaces                 | Continue corpus-driven expansion                   |
| Media accountability       | Relationship, part, content type, byte size, and digest records                                  | Extend with intrinsic dimensions and effective PPI |
| Accessibility seed data    | Picture alt-text inventory and object metadata                                                   | Promote into an evidence-rich preflight report     |

### Need Port As Clean-Room VassilFlow Design

`Port` in this table means reimplement the capability from a VassilFlow-owned
specification. It does not mean translating or copying source.

| Capability                        | VassilFlow adaptation                                                                                                | Priority  |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------- |
| Semantic presentation intent      | Let the model emit slide roles, content, emphasis, and layout intent rather than raw EMU coordinates                 | High      |
| Versioned generation IR           | Introduce a small VassilFlow presentation-generation schema with stable IDs and migrations                           | High      |
| Deterministic layout compiler     | Resolve theme, margins, type scale, fit, alignment, and object geometry in deterministic code                        | High      |
| Read-only quality preflight       | Produce bounded, source-hash-bound findings with evidence and explicit unknowns                                      | Immediate |
| Image effective-PPI checks        | Parse supported image dimensions and account for crop plus final displayed geometry                                  | Immediate |
| Presentation accessibility checks | Report missing alt text, absent slide-title evidence, tiny text, reading-order risks, and unsupported contrast cases | High      |
| Style census                      | Report fonts, sizes, colors, fills, and repeated near-matches before offering harmonization                          | Medium    |
| Semantic Office diff              | Compare before/after object paths, values, relationships, and package parts in addition to byte hashes               | High      |
| Arrange operations                | Add align/distribute/tidy/fit first for generated objects or narrowly selected existing objects                      | Medium    |
| Theme/layout mapping              | Use a VassilFlow-owned model to map generation intent onto native masters, layouts, placeholders, and themes         | Medium    |
| Reversible authoring commands     | Adopt only when an interactive Office editing UI needs undo/redo transactions                                        | Medium    |

### Not Suitable For VassilFlow

| Reference direction                                                | Reason                                                                                                    |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| Direct source or schema port                                       | License boundary and independent-product requirement                                                      |
| Embedding the full editor, backend, database, or realtime stack    | Duplicates the harness architecture and creates a second product/runtime inside VassilFlow                |
| Replacing OOXML preservation with a generic scene graph            | Round-tripping every Office construct through a lossy intermediate model would regress fidelity           |
| Canvas2D as the Office fidelity renderer                           | Browser approximations cannot replace native PowerPoint/WPS/LibreOffice evidence                          |
| Minimal hand-built DOCX output                                     | Too lossy for the current preservation and round-trip contract                                            |
| Simplified sheet formulas as XLSX calculation authority            | Would create silent compatibility and recalculation errors                                                |
| Runtime web-font downloads in render workers                       | Conflicts with deterministic, isolated, no-egress rendering                                               |
| Generic overlap warnings for arbitrary authored PPTX               | Intentional layering would create high false-positive rates                                               |
| Raw unknown-node wrappers as an OOXML mutation strategy            | VassilFlow should preserve unmodified package parts instead of translating unknown XML into generic nodes |
| Identity-bearing package paths, copy, assets, or fallback behavior | Violates VassilFlow's independent product boundary                                                        |

### Defer Until Evidence Is Mature

| Capability                                     | Deferral gate                                                                              |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Full PPTX add/remove/reorder surface           | Generation IR, deterministic compiler, package-diff tests, and PowerPoint/WPS corpus first |
| Tables, charts, notes, and comments writes     | Per-feature native round-trip corpus and typed selectors first                             |
| Transition and animation writes                | Timing-tree corpus, deterministic readback, and renderer evidence first                    |
| Effects, 3D, and custom geometry writes        | Independent OOXML corpus; the reference source does not provide mature Office evidence     |
| Full WYSIWYG editor and realtime collaboration | Proven product need and stable command model first                                         |
| Obstacle-aware connector routing               | Editable-object creation and robust shape bounds first                                     |
| Tagged PDF, video, GIF, or animation export    | Separate export contract and sandboxed renderer evaluation first                           |
| DOCX/XLSX generation IR                        | Mature the PPTX generation lane; share report envelopes, not one universal scene schema    |

## Recommended Roadmap

### H1: PPTX Quality Preflight V1

This is the best next implementation batch because it builds on inspected data,
does not widen mutation authority, and gives both generated and user-authored
presentations a measurable quality gate.

Initial findings should be deliberately narrow:

- Objects fully outside or materially clipped by the slide bounds
- Missing picture alt text, with exact object path and relationship evidence
- Missing slide-title evidence, while distinguishing absence from uncertainty
- Supported PNG/JPEG intrinsic dimensions and crop-aware effective PPI
- Very small direct text sizes where the effective size is known
- Font and color census for later consistency checks
- Explicit `unknown` results for unsupported image formats, inherited sizes,
  composited contrast, and geometry that cannot be resolved safely

Acceptance gates:

- Bind the report to exact source SHA-256 and inspection limits.
- Keep slide, object, issue, and evidence counts bounded.
- Resolve nested-group transforms, flips, rotations, and final displayed size in
  tests before reporting geometry-derived defects.
- Never mutate the package or claim visual review from a preflight pass.
- Avoid generic overlap and contrast auto-fixes in V1.
- Add native PowerPoint/WPS fixtures and adversarial package-limit tests.
- Require inspect, preflight, render, and visual-review stages to remain separate.

#### Implementation Checkpoint: Static Evidence Core

Implemented on 2026-07-16:

- Added a VassilFlow-owned, read-only PPTX quality preflight contract exposed as
  the explicit `pptx_quality_preflight` analysis mode of `office_inspect`.
- Bound every report to the exact source SHA-256 and source size, publish the
  parser scan limits in the report, and apply hard caps of 200 returned
  findings, 200 returned image assessments, and 64 returned values per
  formatting census.
- Added exact-path findings for missing picture descriptions, including
  relationship/part/hash evidence when resolvable; empty title placeholders;
  absence of title-placeholder evidence; very small directly sized shape text
  runs; and low crop-aware effective PPI.
- Initially limited effective-PPI measurements to top-level static PNG or
  baseline JPEG pictures with positive geometry, explicit stretch framing, and
  supported non-negative crop. Grouped pictures and unsupported framing or
  encodings were reported as `unknown` with a reason at this checkpoint.
- Added bounded direct font, text-size, and authored color-token census without
  resolving theme or inherited formatting.
- Kept geometry bounds/overlap and contrast explicitly `unknown` at this
  checkpoint, and stamped visual review as `not_performed` so static evidence
  cannot be presented as visual QA.
- Verified the contract with synthetic limit/adversarial fixtures and both
  native PowerPoint and WPS round-trip corpus files.

Gates carried into the geometry follow-up:

- Resolve cumulative nested-group transforms, flips, rotations, clipping, and
  final display bounds across the native corpus.
- Add adversarial transform fixtures for outside-slide and material-clipping
  detection. Until then these checks remain `unknown`, not inferred defects.

#### H1 Geometry Follow-Up Classification

Re-audited against current VassilFlow code on 2026-07-17:

| Classification  | Direct code evidence and decision                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Already present | `_slide_object_refs` retains the complete nested group tree through stable parent paths. `_object_geometry` parses direct object and group `off`, `ext`, `chOff`, `chExt`, clockwise rotation, and horizontal/vertical flip. Preflight already binds findings to source SHA-256 and exact object paths, measures crop-aware top-level picture PPI, and keeps geometry/overlap explicitly unknown.                                              |
| Implement next  | Add a bounded affine resolver that maps each rectangular object frame through every ancestor group using exact child coordinate spaces, extents, flips, and rotations. Use transformed edge lengths for grouped picture PPI. Report fully outside frames and materially clipped picture frames with exact polygon/slide evidence. Prove the behavior with synthetic adversarial tests and a dedicated PowerPoint/WPS native round-trip corpus. |
| Not appropriate | Generic pairwise overlap warnings, browser-canvas geometry as fidelity authority, geometry mutation, automatic repositioning, or treating a frame intersection as proof that rendered text/custom geometry is clipped.                                                                                                                                                                                                                         |
| Defer           | Rendered text bounds, custom-geometry occupancy, connector strokes/arrowheads, shadows/glows/3D extents, chart/SmartArt internals, masks, and semantic overlap. Keep these unknown until each object family has native evidence or a pixel-backed review contract.                                                                                                                                                                             |

The follow-up remains read-only. A geometry finding is review evidence, not an
automatic defect decision, and visual QA remains mandatory.

#### Implementation Checkpoint: Bounded Geometry Evidence

Implemented and independently reviewed on 2026-07-17:

- Added a fail-closed affine resolver for direct and nested object frames. It
  maps `chOff/chExt` into `off/ext`, applies horizontal/vertical flips before
  clockwise rotation around the outer frame center, composes ancestors outside
  descendants, and derives picture display axes from transformed edges. This
  follows the published [group transform behavior](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/9ce071a0-4053-4714-9025-1951253cab2a).
- Extended supported PNG/baseline-JPEG PPI evidence through nested groups and
  destination `fillRect` insets/outsets. The measured destination rectangle is
  distinct from the object frame, matching the DrawingML
  [`fillRect` contract](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.fillrectangle?view=openxml-3.0.1).
- Added bounded frame polygons, exact slide bounds, clipped polygons, source
  and intersection areas, transformed edge lengths, and visible/outside
  percentages to every measured geometry assessment. Published maximum group
  depth, coordinate, transform, percentage, finding, and assessment limits in
  the report itself.
- Added exact-path warnings for non-group object frames with zero slide
  intersection and informational findings for picture frames at least five
  percent outside the slide. A very large frame that still covers the slide is
  no longer misclassified as fully outside.
- Added synthetic cases for non-commuting anisotropic scale, non-zero child
  coordinates, observable flips, rotation, destination fill insets, huge
  coordinates, and 4,000-digit numeric attributes. Invalid or excessive
  geometry remains explicit `unknown` instead of escaping the bounded report.
- Added the dedicated `tests/fixtures/office/pptx/geometry` corpus. Its seed and
  real Microsoft PowerPoint 16 and WPS Presentation 12 round trips preserve
  exact object paths, group depths, transformed PPI, frame bounds, and clipping
  percentages. All three slides were rendered and visually inspected; the
  PowerPoint render hashes match the seed exactly, while WPS preserves the
  visuals with its known one-pixel slide-width normalization.

The geometry check is now `partial`, not complete: it evaluates affine
rectangular frames only. Generic overlap, rendered text bounds, custom geometry
occupancy, connector strokes, effects/3D, charts, SmartArt, and automatic fixes
remain outside H1.

### H2: Semantic Change Receipt

Extend each Office mutation result with a bounded receipt containing before and
after source hashes, applied operation IDs, changed object paths, changed
relationships/parts, and semantic property deltas. This should complement, not
replace, package-level validation and rendered review.

#### Implementation Checkpoint: Transaction Evidence

Implemented on 2026-07-16:

- Every successful `office_edit` now returns
  `vassilflow.office.semantic_change_receipt.v1`, built from the exact input and
  final in-memory result before the staged output commit.
- The receipt includes exact source/result SHA-256 and byte size, deterministic
  non-payload operation IDs, actual matched object/cell paths captured by each
  format engine, and final before/after semantic property deltas.
- OPC evidence includes content hashes and sizes for added, removed, or changed
  parts plus typed relationship additions, removals, and changes by source part
  and relationship ID.
- Returned operation, target, delta, part, relationship, text, and structured
  values are bounded with explicit counts, limits, truncation flags, and
  semantic coverage state.
- Receipt construction is transactional: failure to produce the evidence
  prevents output commit. Existing package validation remains a separate gate,
  and the receipt does not claim render or visual-review status.

Current boundary:

- Semantic deltas cover the stable typed write surfaces currently supported by
  DOCX, XLSX, and PPTX. Future object families must add their own typed snapshot
  before their mutation surface is opened.
- The receipt describes one edit transaction and is now embedded unchanged in
  an immutable, user-scoped project revision. Exact-parent/source hash guards,
  trusted artifact persistence, and append-only render-preview evidence complete
  the OX1 storage contract; project APIs and UI remain later product batches.

### H3: Presentation Generation IR V1

Define a VassilFlow-owned, versioned schema for slide purpose, content roles,
theme tokens, layout intent, text, image, and simple shape content. The model
must not emit OOXML fragments or unconstrained EMU coordinates. Keep this IR
specific to presentation generation; DOCX and XLSX need different structural
models even if they share diagnostics and artifact envelopes.

### H4: Deterministic Compiler To Editable PPTX

Compile the generation IR into native editable text, image, and simple shape
objects. The gate for every generated deck is:

1. Compile to PPTX.
2. Inspect and validate the package.
3. Run quality preflight.
4. Render in the isolated native pipeline.
5. Review every rendered slide.
6. Reopen and round-trip through PowerPoint and WPS corpus tests.

The current raster-slide generator can remain as an explicit visual-fidelity
fallback during migration, but it must not be mislabeled as editable output.

### H5: Rich Native Objects

Open tables and charts only after the editable text/image/shape compiler is
stable. Each new object family requires its own selector, mutation contract,
semantic diff, package validation, render baseline, and native round-trip corpus.

### H6: Advanced Presentation Semantics

Evaluate transitions, animations, effects, 3D, custom geometry, notes, and
comments independently. Source maturity in a browser design tool is not evidence
of Office round-trip safety, so these remain corpus-driven decisions.

## Risks And Guardrails

- A generated design model and an OOXML preservation model solve different
  problems. Combining them into one universal representation would hide loss.
- Bounding boxes are useful evidence but not complete visual truth for rotated
  text, clipping paths, masks, effects, charts, SmartArt, and grouped content.
- Effective PPI must use visible source pixels after crop and final transformed
  display dimensions. Reporting raw source resolution alone is misleading.
- Contrast requires composited pixels or a narrowly proven solid-background
  case. Unknown is safer than a confident but false accessibility result.
- Native rendering is still not semantic correctness; preflight is still not
  visual review. Both gates are required.
- AI generation should produce intent and content. Deterministic code must own
  layout, package serialization, limits, and validation.

## Verification Notes

- The reference checkout was read at the exact commit recorded above and left
  clean after research.
- A dependency install attempt was interrupted and was not used as test
  evidence; partial `node_modules` directories were removed.
- Reference test sources were inspected, but no reference test result is claimed.
- This audit changes no Office runtime, public docs, local configuration, or
  secrets.

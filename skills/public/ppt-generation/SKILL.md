---
name: ppt-generation
description: Create new editable native PPTX presentations with VassilFlow Office tools, then inspect, render, and visually verify every slide before delivery.
---

# Native PPTX Generation

Use `office_generate` for every new presentation unless the user explicitly asks for a flattened, image-only deck. The generated PPTX contains editable native text boxes, pictures, and simple shapes. It also creates an Office Project with a trusted initial revision, semantic generation receipt, and static preflight evidence.

## Required Workflow

1. Turn the request into a concise presentation story and choose one semantic layout per slide.
2. Put referenced image assets under `/mnt/user-data/uploads`, `/mnt/user-data/workspace`, or `/mnt/user-data/outputs`.
3. Call `office_generate` with versioned semantic intent and a new `.pptx` path under `/mnt/user-data/workspace` or `/mnt/user-data/outputs`.
4. Check `ok`, `commit_status`, the project and revision IDs, generation receipt, validation, and complete preflight. Do not continue if preflight has errors or truncated findings.
5. Call `office_inspect` on the generated output and confirm the intended slide count, text, pictures, and stable object paths.
6. Call `office_render` in windows until every slide is rendered. Use a new output directory for each render attempt.
7. In a separate model step, inspect every returned PNG with `view_image`. Look for clipping, overflow, unreadable contrast, awkward image crops, accidental repetition, and inconsistent hierarchy.
8. Use `office_edit` only for exact-path corrections supported by the existing write contract, then inspect and render the new revision again.
9. Call `present_files` only after all pages have passed visual review. Present the PPTX, not the internal QA images.

Never claim that a presentation passed visual QA based only on package validation, preflight, or a render manifest. Those are evidence inputs; every rendered page still requires visual inspection.

## Semantic Intent

The compiler owns geometry. Intent must not contain coordinates, arbitrary XML, slide part names, relationship IDs, or raw formatting instructions.

Supported layouts and content roles:

| Layout | Required roles | Optional roles |
| --- | --- | --- |
| `title` | `title` | `subtitle` |
| `title_content` | `title`, `content` | none |
| `two_column` | `title`, `left`, `right` | none |
| `picture_caption` | `title`, image `media`, `caption` | none |
| `closing` | `title` | `subtitle` |

Every slide needs a stable lowercase ID, a short purpose, and one non-bulleted text title. Element IDs must be unique across the entire presentation. IDs use lowercase letters, digits, `_`, or `-`, start with a letter, and are at most 48 characters.

Text elements accept exactly one of `text` or `bullets`. Image elements require an accessible `alt_text` and use `contain` or `cover`. Simple decorative shapes use compiler-owned placements `accent_bar`, `top_right`, or `bottom_left` and theme color tokens.

Example request:

```json
{
  "intent": {
    "schema": "vassilflow.office.presentation_intent.v1",
    "title": "Quarterly Review",
    "aspect_ratio": "16:9",
    "theme": {
      "background": "F7F8FA",
      "surface": "FFFFFF",
      "text": "17212B",
      "muted": "56616F",
      "accent": "1F6FEB",
      "accent_alt": "0F766E",
      "heading_font": "Arial",
      "body_font": "Arial"
    },
    "slides": [
      {
        "id": "opening",
        "purpose": "Open the review",
        "layout": "title",
        "elements": [
          {
            "kind": "shape",
            "id": "opening-accent",
            "placement": "accent_bar",
            "shape": "rectangle",
            "fill": "accent"
          },
          {
            "kind": "text",
            "id": "opening-title",
            "role": "title",
            "text": "Quarterly Review"
          },
          {
            "kind": "text",
            "id": "opening-subtitle",
            "role": "subtitle",
            "text": "Decisions, evidence, and next actions"
          }
        ]
      },
      {
        "id": "summary",
        "purpose": "Summarize the evidence",
        "layout": "title_content",
        "elements": [
          {
            "kind": "text",
            "id": "summary-title",
            "role": "title",
            "text": "Executive summary"
          },
          {
            "kind": "text",
            "id": "summary-points",
            "role": "content",
            "bullets": [
              "Retention improved across core accounts",
              "Delivery reliability remained above target",
              "Two decisions are required"
            ]
          }
        ]
      }
    ]
  },
  "output_path": "/mnt/user-data/outputs/quarterly-review.pptx",
  "overwrite_output": false
}
```

Allowed fonts are `Aptos`, `Arial`, `Calibri`, `Georgia`, `Liberation Sans`, and `Noto Sans`. Theme colors use six hexadecimal RGB digits without `#`. Keep slide content concise enough for the semantic layout; the compiler rejects text that cannot remain readable.

## Images

Use images only when they carry evidence or meaning. Store each source under `/mnt/user-data`, provide specific alt text, and choose:

- `contain` when the whole image must remain visible.
- `cover` when filling the semantic media region matters more than preserving every edge.

Generation accepts bounded PNG and baseline JPEG assets. It rejects progressive JPEG, unsupported encodings, oversized images, network URLs, data URIs, and inline base64. Prefer a relevant source image or a generated bitmap over decorative filler.

## Revisions And Follow-Up Edits

Keep the returned `project_id`, `revision_id`, source SHA-256, stable object paths, receipt, and render evidence together. Use the current project revision for follow-up edits. Re-inspect before editing if another revision may have changed the artifact.

An `office_edit` call creates a new revision with its own semantic change receipt. Render and review that revision before presenting it. Initial generated revisions have no parent comparison; later edit and restore revisions do.

## Flattened Fallback

`scripts/generate.py` is a legacy raster-composition fallback. It puts one image on each slide, so text and visual elements are not independently editable. Use it only when the user explicitly requests image-only slides or when preserving an already-rendered slide exactly is the stated goal.

The fallback requires `acknowledge_flattened_output=True` in Python or `--acknowledge-flattened-output` on the command line. Its result reports `output_mode: raster_composite` and `editable_objects: false`. Never describe that output as native or editable.

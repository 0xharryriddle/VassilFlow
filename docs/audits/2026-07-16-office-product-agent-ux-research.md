# VassilFlow Office Product, Agent, And Template UX Research

Date: 2026-07-16
Status: Product and architecture recommendation

## Scope

This research answers four related questions:

1. Should Office be exposed only through chat, as a dedicated Agent, or as a
   first-class workspace?
2. How should VassilFlow organize lead agents, user agents, internal workers,
   skills, tools, templates, and projects without collapsing them into one
   concept?
3. How should a company save Office templates and reuse only approved variable
   regions while preserving everything else?
4. What UI can be added incrementally without bypassing the current Office
   engine, sandbox, source guards, rendering, and visual-QA gates?

External products are used only as product references. Their UI, source,
wording, identity, schemas, and assets must not be copied into VassilFlow.

## Current VassilFlow Evidence

The recommendation is based on the current implementation, not an abstract
multi-agent model.

### Current User-Facing Agent

VassilFlow already has a user-facing custom Agent abstraction:

- `AgentConfig` stores a name, description, optional model, tool-group
  whitelist, and skill whitelist.
- Each user Agent has its own `SOUL.md` and memory file.
- The Agent gallery launches a dedicated chat route bound to `agent_name`.
- Agent creation is conversational: a bootstrap chat gathers the definition,
  then `setup_agent` persists it.

Relevant paths:

- `backend/packages/harness/vassilflow/config/agents_config.py`
- `backend/app/gateway/routers/agents.py`
- `frontend/src/components/workspace/agents/agent-gallery.tsx`
- `frontend/src/app/workspace/agents/new/page.tsx`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`

### Current Lead Agent And Skills

The default lead Agent resolves a model, filters tools by tool group, filters
skills by Agent policy, loads skills on demand, and assembles middleware for
memory, clarification, vision, summarization, safety, and subagent limits.

Skills are reusable instruction packages. They can constrain allowed tools and
contain references, templates, scripts, and assets, but their current product
UI is primarily an enable/disable settings list. Explicit skill invocation is
available through slash-style discovery in the chat input.

Relevant paths:

- `backend/packages/harness/vassilflow/agents/lead_agent/agent.py`
- `backend/packages/harness/vassilflow/skills/types.py`
- `backend/packages/harness/vassilflow/skills/tool_policy.py`
- `frontend/src/components/workspace/settings/skill-settings-page.tsx`
- `frontend/src/components/workspace/input-box.tsx`

### Current Internal Workers

VassilFlow also has a separate subagent system. These are isolated runtime
workers invoked by the lead Agent through `task`. Built-in and config-defined
workers have system prompts, model/tool/skill policies, turn limits, and
timeouts. They are not the same object as user-created Agents, even though both
areas currently use the word `agent` in code and configuration.

Relevant paths:

- `backend/packages/harness/vassilflow/subagents/registry.py`
- `backend/packages/harness/vassilflow/config/subagents_config.py`
- `backend/packages/harness/vassilflow/tools/builtins/task_tool.py`

### Current Office Capability

Office is currently a capability layer, not a product workspace or Agent:

- `office_inspect` is in `file:read`.
- `office_edit` and `office_render` are in `file:write`.
- The lead Agent or any permitted custom Agent may call these tools.
- The public PPT generation skill currently creates raster slide images and
  composes them into a PPTX; it does not yet compile editable native objects.
- Office files appear as generic artifacts. The artifact panel can preview
  PDFs, images, audio, and video in-browser, but DOCX/XLSX/PPTX currently fall
  back to download.
- Workspace Changes recognizes Office files as binary files and cannot yet
  present a semantic Office diff.

Relevant paths:

- `backend/packages/harness/vassilflow/community/office/`
- `backend/docs/OFFICE_TOOLS.md`
- `skills/public/ppt-generation/SKILL.md`
- `skills/public/ppt-generation/scripts/generate.py`
- `frontend/src/components/workspace/artifacts/artifact-file-detail.tsx`
- `frontend/src/core/utils/files.tsx`
- `frontend/src/components/workspace/changes/workspace-change-panel.tsx`

### Current State Boundary

Files are isolated by user and thread. Each thread receives its own uploads,
workspace, outputs, and ACP workspace directories mounted into the sandbox.
Agents and memory are user-scoped, but there is no first-class Office project,
template library, brand kit, or reusable binary asset model.

Relevant path:

- `backend/packages/harness/vassilflow/config/paths.py`

## Product Research

The following sources were read on 2026-07-16.

### Genspark

Primary sources:

- https://www.genspark.ai/helpcenter?doc=general_What_Is_Genspark
- https://www.genspark.ai/helpcenter/ai-slides
- https://www.genspark.ai/helpcenter/ai-docs
- https://www.genspark.ai/helpcenter/ai-sheets
- https://www.genspark.ai/helpcenter/custom-super-agent
- https://www.genspark.ai/helpcenter/skills
- https://www.genspark.ai/helpcenter/hub
- https://www.genspark.ai/helpcenter/workflows
- https://www.genspark.ai/docs/ai_slides_changelog

Observed product pattern:

- A general Super Agent remains the broad entry point and coordinates
  specialized capabilities.
- Slides, Docs, and Sheets each have a dedicated entry in the New/sidebar
  navigation and a format-appropriate working surface.
- Custom Agents have a separate store/gallery and can be invoked from a general
  conversation using `@`.
- Skills are reusable expert workflows that can be selected independently of
  Agents. They have community, organization, and personal scopes.
- A Hub is persistent shared context: files, instructions, project history, and
  members. It is not an Agent.
- Workflows are scheduled or event-triggered automation and are managed
  separately from Agents and Skills.

Format-specific interaction is especially relevant:

- Slides combines chat with a slide surface, targeted edit actions, preview,
  save points, templates/skills, and export.
- Docs allows selected text to become scoped chat context, supports manual
  editing, and creates save points.
- Sheets allows a selected cell range to be sent to chat and keeps a spreadsheet
  editor as the primary working surface.
- A guided creation mode gathers structured decisions before generation, while
  a fast mode accepts one prompt and proceeds.
- Recent projects and reusable skills/templates are visible near the creation
  entry instead of being hidden inside settings.

The useful lesson is the separation of product nouns and interaction surfaces,
not the number of named agents or the specific UI styling.

### Microsoft 365

Primary sources:

- https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-agent-store
- https://learn.microsoft.com/en-us/microsoft-365/copilot/agent-essentials/m365-agents-admin-guide
- https://learn.microsoft.com/en-us/sharepoint/organization-assets-library
- https://learn.microsoft.com/en-us/sharepoint/connect-organizational-asset-libraries-to-copilot
- https://support.microsoft.com/en-us/powerpoint/use-your-organization-s-templates-in-powerpoint
- https://support.microsoft.com/en-us/powerpoint/create-and-save-a-powerpoint-template
- https://support.microsoft.com/en-us/word/edit-templates
- https://support.microsoft.com/en-us/excel/save-a-workbook-as-a-template

Observed product pattern:

- Agent discovery is centralized in a store, while administrators review
  publisher, users, data/tools, security, certification, and activity before
  organization deployment.
- Organization templates and image assets are centrally managed resources with
  permissions and metadata, not embedded in an Agent prompt.
- Native Office template semantics differ by format: PowerPoint masters,
  layouts, and placeholders; Word content controls and building blocks; Excel
  workbook templates and named structures.
- Organization templates are selected when creating a file, and Copilot can use
  the selected brand/template context.

### Canva

Primary sources:

- https://www.canva.com/for-teams/features/brand/
- https://www.canva.com/for-teams/team-templates/
- https://www.canva.com/newsroom/news/home-for-every-brand/

Observed product pattern:

- Brand Kit, Brand Templates, Brand Assets, Brand Guidelines, Brand Controls,
  and approvals are separate but connected concepts.
- Template creators may lock logos or other fixed elements while leaving
  intended regions editable.
- Admin controls can restrict fonts and colors.
- Templates are checked before publication, and teams use published templates
  rather than editing a shared source directly.

### Gamma And Beautiful.ai

Primary sources:

- https://help.gamma.app/en/articles/12590858-how-do-i-use-workspace-templates
- https://help.gamma.app/en/articles/11029150-can-i-add-my-own-colors-and-fonts-to-gamma
- https://support.beautiful.ai/hc/en-us/articles/4405716068365-Team-Template-Overview
- https://support.beautiful.ai/hc/en-us/articles/5671414223757-Team-Assets
- https://support.beautiful.ai/hc/en-us/articles/360048192991-Team-Theme-Overview

Observed product pattern:

- Workspace templates are independent reusable starting points, commonly
  duplicated or remixed without modifying the original.
- Themes are reusable visual policy and can be shared across a workspace.
- Templates, shared slides/components, themes, and assets have different update
  semantics.
- Editing a template does not necessarily update derived presentations, while a
  centrally linked asset may support an explicit organization-wide update.

This distinction is important for VassilFlow: a template version should produce
an auditable snapshot, while a project may later opt into an explicit asset or
template upgrade with a reviewed diff. Silent retroactive mutation would be
unsafe for exported Office deliverables.

## Required Product Vocabulary

VassilFlow should make these concepts distinct in code, API, and UI.

| Concept                | Responsibility                                                          | User-facing?                      | Office example                                      |
| ---------------------- | ----------------------------------------------------------------------- | --------------------------------- | --------------------------------------------------- |
| Tool                   | One bounded machine action                                              | Usually shown only in activity    | Inspect a PPTX, apply typed edits, render pages     |
| Skill                  | Reusable method/playbook                                                | Yes, in a library and picker      | Quarterly board-deck workflow                       |
| Template               | Versioned source artifact plus editable-slot policy                     | Yes, in Office library            | Company proposal PPTX with approved variable fields |
| Brand profile          | Fonts, colors, logos, imagery, and usage rules                          | Yes, managed resource             | Corporate identity used by several templates        |
| Project                | Persistent work, files, revisions, QA, and conversation                 | Yes, primary Office object        | Q3 sales proposal based on template v4              |
| Agent                  | Persistent interactive role with model, permissions, skills, and memory | Yes, in Agent gallery             | Sales proposal specialist                           |
| Domain runtime profile | Curated built-in Agent behavior behind a product surface                | Usually implicit                  | Office authoring runtime used by Office Studio      |
| Worker                 | Internal isolated execution context                                     | Activity only, not a gallery card | Research or visual-QA worker                        |
| Workflow               | Triggered repeatable automation with run history                        | Yes when implemented              | Generate a monthly report on schedule               |

Decision rule for users and developers:

| Need                                                        | Correct abstraction |
| ----------------------------------------------------------- | ------------------- |
| Perform one exact operation                                 | Tool                |
| Reuse instructions and output standards                     | Skill               |
| Preserve a file's structure and replace approved fields     | Template            |
| Reuse approved visual identity across templates             | Brand profile       |
| Continue work over time with revisions                      | Project             |
| Keep an interactive expert role, memory, and permission set | Agent               |
| Delegate hidden parallel work                               | Worker              |
| Run repeatedly from a schedule/event                        | Workflow            |

## Main Decision

Office should be a **first-class domain workspace backed by a curated Office
Agent runtime profile**.

It should not be only a generic chat feature, and it should not be only another
card in the custom Agent gallery.

The distinction is:

- **Office Studio** is the product surface: projects, templates, previews,
  revisions, change review, QA, and export.
- **Office Agent** is the bounded reasoning/runtime profile used inside that
  surface.
- **Office tools** remain the only mutation and rendering authority.
- **Office skills** define reusable ways of working.
- **Office templates and brand profiles** remain versioned data resources.

The exact public label can be decided later. `Office Studio` and `Office Agent`
are working VassilFlow-native names in this research document.

### Why Chat Alone Is Insufficient

Chat is excellent for intent, clarification, research, and iterative direction,
but poor at showing persistent document state:

- Which template and version are active?
- What slide/page/range is selected?
- Which fields are locked or variable?
- What changed in the last revision?
- Has the current source passed package validation, preflight, render, and visual
  review?
- Which output is the current approved artifact?

These states need a stable UI outside the message transcript.

### Why A Standalone Agent Card Is Insufficient

The existing Agent card launches a specialized chat. That is useful for roles,
but it does not provide a project library, template management, document canvas,
selection context, revision timeline, or QA status. Making Word, Excel, and
PowerPoint three Agent cards would also confuse formats with professional roles.

### Why A Domain Agent Is Still Useful

A curated Office runtime profile gives the domain surface a stable model/tool/
skill policy:

- Default access to Office inspect, edit, render, preflight, file presentation,
  and approved read/write operations
- Optional web and image research when explicitly enabled
- No generic host shell by default
- Office-specific prompt and clarification behavior
- Access to selected template, brand profile, and project revision context
- Domain memory for soft user preferences, not as a source of truth for brand
  or template data

Users may later invoke this profile from general chat, but the work product
should still open as an Office project.

## Recommended Information Architecture

### Primary Navigation

Keep the sidebar compact:

- Chats
- Office
- Agents
- Recent items, scoped to the selected section

Add a single New command that opens a menu:

- Chat
- Presentation
- Document
- Spreadsheet
- Agent
- Skill

Do not add permanent Word, Excel, and PowerPoint sidebar sections. They are
creation modes inside Office.

### Office Home

The first Office screen should be the actual working entry, not a marketing
landing page.

Top-level views:

- `Recent`: Office projects with preview, format, current QA state, template,
  and last update
- `Templates`: reusable Office sources, filterable by format and status
- `Brand`: approved fonts, colors, logos, images, and rules when this model is
  implemented

Primary create controls:

- New presentation
- New document
- New spreadsheet
- Use template
- Import existing file

Template and project cards are appropriate repeated items. Page sections should
remain unframed and dense enough for scanning.

### Agent Gallery

The Agent gallery should remain role-oriented. Future filters may distinguish:

- Built-in
- Mine
- Organization

A built-in Office Agent may appear here as an alternate entry point, but opening
it should offer `Start Office project`, not trap the user in a chat-only view.
User-created Agents such as a sales-proposal specialist may select Office
skills, allowed tools, and default resource references.

Do not expose internal research, layout, conversion, or QA workers as Agent
cards. They are implementation details shown only as task activity.

## Interaction Model

VassilFlow should support three entry paths that converge on one project model.

### 1. General Chat

The user may ask the lead Agent to create or edit an Office file. The lead Agent
uses Office tools or skills directly. As soon as durable Office work begins, the
run creates or links an Office project and the artifact offers `Open in Office`.

This preserves the low-friction super-agent behavior.

### 2. Office Studio

The user chooses a format, source, or template first. The Office runtime profile
is already active, the project state is visible, and chat is used for intent and
refinement rather than navigation.

This is the preferred path for complex, recurring, branded, or review-heavy
work.

### 3. Explicit Agent Invocation

After VassilFlow has a unified invocation contract, general chat may support an
Agent picker or `@` invocation. This should attach an Agent reference to the
run; it should not rely on parsing plain text after submission.

Current user Agents and internal subagents are separate registries, so this
must not be implemented as a shallow frontend mention menu. Backend invocation
must preserve user identity, tool policy, skills, limits, sandbox, trace, and
non-recursive delegation rules.

## Office Project UI

### Desktop Layout

Use a stable work surface with three regions:

```text
+----------------+--------------------------------------+------------------+
| Structure      | Document canvas                      | Conversation     |
|                |                                      | and activity     |
| Slide thumbs   | Current rendered page/slide/sheet    |                  |
| Document map   | Selection overlay when supported     | Selected context |
| Sheet tabs     | Before/after or revision comparison  | Prompt           |
+----------------+--------------------------------------+------------------+
```

The header should contain only project commands and state:

- Back
- Project title
- Template/version indicator
- Preflight/review status
- Revision history
- Export/present

The current source SHA and exact object path belong in a details panel, not as
the primary visible label.

### Mobile Layout

Do not compress three panes side by side. Use tabs or a bottom navigation for:

- Preview
- Chat
- Changes

Slide/page navigation remains a horizontal thumbnail strip. Editing a complex
sheet may be view-only on mobile until a mobile grid interaction is proven.

### Selection-To-Chat

The strongest common interaction across document products is selection-scoped
AI editing:

- PPTX: click a rendered object overlay or choose an object from the structure
  tree.
- DOCX: select a paragraph/run/content control when a safe document view exists.
- XLSX: select a cell range when a grid view exists.

The prompt shows a removable context chip such as `Slide 4 / Summary title`.
Submission sends a typed selector and source fingerprint alongside the user's
instruction. The model should not reconstruct selectors from visible labels.

For the first PPTX UI, a native render plus inspection-derived object overlays
is enough. A full drag-and-drop WYSIWYG editor is not required to expose useful,
precise editing.

### Change Review

Office changes need a domain review panel rather than the generic binary-file
message:

- Proposed operations before apply
- Exact semantic paths and old/new values
- Package parts and relationships touched
- Before/after render toggle
- Preflight findings introduced/resolved
- Apply, discard, or remove one proposed operation
- Current visual-review state

This should extend the existing Workspace Changes and artifact side panel
patterns instead of creating an unrelated notification system.

### Revisions

Every successful Office mutation creates an immutable project revision with:

- Parent revision ID
- Input and output SHA-256
- Applied operation receipt
- Semantic diff
- Package validation result
- Preflight result
- Render manifests
- Visual-review status
- Template and brand versions

The UI calls these revisions or save points. Rollback creates a new revision
from an older source; it does not delete history.

## Template And Brand System

### Template Is Not A Skill

A skill may refer to a template, but a binary template must not be stored only
inside a prompt package:

- Templates need independent ownership, permission, preview, validation,
  version, publication, and archival state.
- A skill describes how to work; a template defines the exact source artifact
  and allowed variable surface.
- Brand resources may be shared by many templates and skills.

### Template Version Model

Each published template version is immutable:

- Template ID and version
- Owner and scope (`user` first; organization later)
- Format and native source filename
- Source blob and SHA-256
- Package inspection summary
- Render preview manifest and thumbnails
- Slot schema
- Locked-region policy
- Optional brand-profile version
- Compatibility and QA status
- Created/published/archived metadata

Creating from a template always starts from the exact published bytes. Updating
a template creates a new version. Existing projects remain pinned until a user
explicitly requests an upgrade and reviews its diff.

### Slot Model

Every variable region needs a stable key and typed contract:

- `key` and human label
- Type: text, rich text, image, number, date, choice, table data, or range data
- Exact format-specific selector
- Expected source metadata and fingerprint
- Required/optional
- Cardinality
- Length, aspect-ratio, data-shape, or choice constraints
- Allowed operation types
- Default value and instructional hint

Region policies:

- `locked`: preserve exactly
- `slot`: may change only through its typed binding
- `agent_managed`: Agent may propose changes, but still through a bounded
  selector and reviewed operation
- `optional`: may be cleared within the supported structural contract
- `repeatable`: future capability requiring proven object cloning/insertion

Locks must be enforced by the operation validator and post-edit semantic/package
diff. A prompt saying "do not change the logo" is not a lock.

### Format-Specific Slot Sources

Use native semantics before inventing markers:

| Format | Preferred slot sources                                                                       | V1 readiness                                     |
| ------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| PPTX   | Placeholders, authored shape IDs/names, picture relationships, selected text runs/paragraphs | Best first target                                |
| DOCX   | Content controls, bookmarks, building-block regions, then exact paragraph/run selectors      | Defer runner until content-control corpus exists |
| XLSX   | Named ranges, tables, existing cells, protected regions                                      | Defer runner until value/formula editing is safe |

For PPTX Template V1, support only existing text and picture slots in a fixed
slide structure. Do not promise repeated slides, added objects, chart binding,
or slide reordering until those write surfaces have their own corpus.

### Template Import UI

Use a short, explicit workflow:

1. **Upload**: select PPTX and run package/security validation.
2. **Preview**: render every slide and show source metadata.
3. **Map fields**: detect candidates, then let the owner mark variable and
   locked regions and define types/constraints.
4. **Validate**: run selector resolution, duplicate-key checks, preflight,
   render, and native compatibility gates.
5. **Publish**: save an immutable version or keep it as draft.

The Template detail view should expose:

- Preview and slide thumbnails
- Slots
- Versions
- QA/compatibility
- Ownership and access

Actions:

- Use
- Edit draft mapping
- Create new version
- Duplicate
- Archive

### Using A Template

Starting a project from a template should combine form and chat:

- A generated form collects required typed slots efficiently.
- Chat handles ambiguous content, research, rewriting, and multi-step intent.
- Values entered in either surface update one project brief.
- The user approves an outline or binding summary before expensive generation.
- VassilFlow clones the exact template version, applies allowed operations,
  rejects any out-of-policy change, renders, and opens a comparison.

This is more reliable than asking users to describe every field in one prompt,
while preserving a conversational path for users who prefer it.

### Updating Only Changed Content

For recurring reports, the user may choose a prior project revision as the data
baseline. The Agent proposes a binding delta:

- Changed slot values
- Unchanged slot values
- Missing required inputs
- Values derived from newly attached data

Only approved changed slots are submitted to `office_edit`. Unchanged content
is preserved from the exact template/project source. The output receipt must
prove that no locked region or unrelated package part changed.

### Brand Profile

Keep reusable brand policy separate from the template:

- Fonts and approved fallbacks
- Color tokens
- Logos and approved image assets
- Image style guidance
- Tone and terminology guidance
- Usage rules and prohibited combinations
- Owner, scope, version, and status

Templates may pin a brand-profile version. A brand update does not silently
rewrite completed projects. The UI may offer `Upgrade brand version`, followed
by semantic diff, render, and review.

## Agent Organization Recommendation

### Lead Agent

Keep one general lead Agent as the default entry. It may use Office skills and
tools directly for ordinary requests and create an Office project when durable
document work starts.

### Built-In Domain Agents

Introduce a small curated set only where a domain has:

- A distinct permission policy
- Persistent domain state
- A dedicated work surface
- Specialized clarification and quality gates

Office meets this bar. Word, PowerPoint, and Excel individually do not need
separate default Agents; they are modes under the Office domain profile.

### User Agents

Keep custom Agents role- or outcome-oriented, for example a proposal specialist
or financial-review specialist. Extend the model later with permission-checked
resource references:

- Default skills
- Optional default template IDs
- Optional brand profile ID
- Knowledge/file collection references

Do not embed template binaries or brand source-of-truth data into `SOUL.md` or
memory.

### Internal Workers

Rename them conceptually to workers in product documentation and activity UI,
even if existing internal APIs retain `subagent` for compatibility. Workers are
selected by the lead/domain Agent for bounded tasks such as research, data
analysis, layout compilation, or visual QA.

Workers must remain hidden from the user Agent gallery and inherit the parent
identity, sandbox, tool-group ceiling, skill ceiling, trace, and token limits.

### Agent Registry Gap

Current user Agents and config-defined subagents have different storage and
execution contracts. Before adding `@Agent` invocation, define a unified
read-side catalog and explicit invocation projection:

- Stable Agent ID and display metadata
- Origin: built-in, user, or organization
- Editable/deletable flags
- Capabilities and output types
- Tool/skill/resource policy
- Conversation starters
- Version and publication status
- A restricted worker projection for invocation from another Agent

Do not make user Agents directly callable as internal workers without removing
clarification, presentation, recursive delegation, and unsafe tools.

## Backend Integration

### Project And Library Storage

Do not overload a thread as the durable Office project. A project may contain
multiple revisions and eventually multiple conversations. It may keep a
`primary_thread_id` initially to reuse the current streaming UI.

Suggested user-scoped storage boundary:

```text
{base_dir}/users/{user_id}/office/
  templates/{template_id}/versions/{version}/
  brands/{brand_id}/versions/{version}/
  projects/{project_id}/revisions/{revision_id}/
```

The template/brand library must not be mounted wholesale into an agent sandbox.
A typed backend operation materializes one permission-checked template version
or asset into the current thread workspace. Final project revisions are copied
back through a trusted backend path with hashes and receipts.

This preserves the current thread sandbox isolation.

### API Surface

Candidate resource APIs:

- `GET/POST /api/office/projects`
- `GET/PATCH /api/office/projects/{project_id}`
- `GET /api/office/projects/{project_id}/revisions`
- `POST /api/office/projects/{project_id}/revisions/{revision_id}/restore`
- `GET/POST /api/office/templates`
- `GET /api/office/templates/{template_id}`
- `POST /api/office/templates/{template_id}/versions`
- `POST /api/office/templates/{template_id}/versions/{version}/publish`
- `POST /api/office/templates/{template_id}/instantiate`
- `GET/POST /api/office/brands`

Tool calls should remain narrower than management APIs. Candidate runtime tools:

- `office_preflight`
- `office_template_inspect`
- `office_template_instantiate`
- Existing `office_inspect`, `office_edit`, and `office_render`

Template publication and permission management should not be ordinary Agent
tools in the first release.

### Runtime Context

Office project runs should receive trusted server-side context, not prompt text:

- Project ID
- Current revision ID and source SHA-256
- Selected template/version ID
- Selected brand/version ID
- Selected object paths or cell range
- Allowed slot keys and operation types
- Review and preflight state

The current lead Agent and worker identity/tool policy must still apply.

### Frontend Routes

Candidate routes:

- `/workspace/office`
- `/workspace/office/projects/{project_id}`
- `/workspace/office/templates/{template_id}`
- `/workspace/office/templates/new`
- `/workspace/office/brands/{brand_id}`

The first project view can reuse the current chat stream, artifact side panel,
workspace change panel, and Office render artifacts. A dedicated three-region
project layout can follow without replacing the backend contract.

## Security And Governance

- Treat uploaded templates as untrusted Office packages and apply the current
  active-content, relationship, ZIP/XML, and size policies.
- Do not inject hidden text, notes, comments, custom XML, or template metadata
  into the model prompt without an explicit bounded inspection path.
- Bind every template version and project revision to SHA-256.
- Resolve template access server-side for the effective user.
- Keep personal scope first. Add organization publishing only with an explicit
  membership, role, approval, and audit model.
- Separate `can use`, `can edit draft`, `can publish`, and `can administer`.
- Record who published each version and which Agent/model/tool operations
  produced each revision.
- Do not automatically update completed outputs when a template, logo, theme,
  or brand profile changes.
- Never accept a prompt-level instruction as authority to unlock a template
  region.

## Decision Table

| Question                                       | Decision                                                                                                   |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Should Office be an Agent?                     | Use a curated Office domain Agent behind a first-class Office workspace; do not expose Office only as chat |
| Separate Word/Excel/PowerPoint Agents?         | No; use format modes and skills under one Office domain                                                    |
| Keep Office available from general chat?       | Yes; general chat creates/links an Office project when durable work begins                                 |
| Add `@Office` immediately?                     | Defer until user-Agent and worker invocation contracts are unified                                         |
| Store company templates as skills?             | No; templates are versioned binary resources that skills may reference                                     |
| Use a form or chat for template filling?       | Both: typed form for required slots, chat for intent and refinement                                        |
| Let prompts enforce fixed content?             | No; enforce locks through selector allowlists and post-edit diffs                                          |
| Build full WYSIWYG now?                        | No; start with render preview, structure navigation, selection overlays, and typed edits                   |
| Auto-update old outputs when template changes? | No; offer an explicit reviewed upgrade                                                                     |
| Implement all formats together?                | No; start with fixed-structure PPTX text/picture slots                                                     |
| Put templates in Settings?                     | No; templates and recent projects belong in the Office working surface                                     |
| Show internal workers in Agent gallery?        | No; show them only as bounded run activity                                                                 |

## Recommended Delivery Batches

### OX1: Quality And Revision Contracts

- Implement PPTX Quality Preflight V1 from the capability audit.
- Add semantic Office change receipts.
- Define immutable Office revision metadata.
- Extend Office artifacts with render-preview metadata.

This backend evidence should exist before a polished Office management UI.

#### Implementation Checkpoint: PPTX Quality Evidence

Implemented on 2026-07-16:

- The first OX1 contract is available through
  `office_inspect(analysis_mode="pptx_quality_preflight")` without adding a
  second sandbox transport or changing local tool configuration.
- Reports are immutable-source evidence: exact SHA-256, bounded findings,
  bounded image measurements, direct formatting census, explicit unknowns, and
  `visual_review_status="not_performed"`.
- The built-in Office Agent now advertises and invokes this real runtime mode,
  while preserving inspect, preflight, render, and visual review as separate
  stages.
- Every successful `office_edit` now returns a bounded, pre-commit semantic
  receipt with exact source/result SHA-256, deterministic operation IDs, actual
  object paths, net property deltas, and changed OPC parts/relationships.
- Receipt evidence is format-owned for current DOCX, XLSX, and PPTX write
  surfaces, carries explicit limits/truncation state, and cannot be replaced by
  a model-authored summary. Receipt failure prevents output commit.
- Every successful `office_edit` now also creates or advances a user-scoped
  Office project under the trusted backend path
  `{base_dir}/users/{user_id}/office/projects/{project_id}`. This path is not a
  sandbox mount and is resolved from authenticated runtime context.
- A new project publishes an immutable baseline revision for the exact input
  bytes and an immutable edit revision for the result. Every revision stores a
  native artifact, exact SHA-256 and size, parent and sequence, source/result
  workspace provenance, the complete bounded semantic receipt, package
  validation, and honest commit-time QA states. Missing preflight, render, and
  visual-review evidence is recorded as not performed rather than inferred.
- Continuing a project requires both its backend-generated project ID and exact
  current parent revision ID. The source bytes must match the current parent's
  artifact hash and size. A stale parent, wrong format, malformed ID, tampered
  artifact, or mismatched receipt fails closed before the requested workspace
  output is replaced.
- Revision directories are append-only and project pointers use atomic replace.
  Per-project in-process and cross-process file locks serialize writers. A
  failed pointer update may leave an unselected immutable revision for recovery,
  but it cannot advance the current project pointer silently.
- The trusted revision is the canonical commit and is persisted before
  materializing `output_path`. If sandbox replacement fails afterward,
  `office_edit` returns `revision_committed_output_failed` together with the
  durable project/revision IDs instead of hiding the partial transaction.
- `office_render` can now bind a render to both a project ID and exact revision
  ID. It verifies the source bytes against that immutable artifact before
  invoking the renderer, so stale or unrelated files cannot become revision
  previews.
- Bound renders publish append-only
  `vassilflow.office.render_evidence.v1` records under the trusted project. Each
  record stores the complete source-bound render manifest, renderer/pipeline
  identity, page window, honest visual-review status, and trusted copies of all
  preview PNGs with SHA-256, size, dimensions, and source-slide identity.
- Render evidence lives at project level and references a revision rather than
  mutating the closed revision directory. The store exposes verified read and
  bounded list operations suitable for a later project API. Thread-local renders
  remain supported when both IDs are omitted, but they do not claim durable
  project evidence.
- The trusted render record is published before the thread manifest. If the
  latter fails, `office_render` returns
  `render_evidence_committed_output_failed` and the durable evidence ID. A
  project surface can therefore recover the preview without treating an
  incomplete thread render directory as valid.

OX1 is now complete at the contract and trusted-storage layer. OX2 can start on
top of these real records; no placeholder Office project route or management UI
is advertised yet.

### OX2: Office Entry And Preview

- Add one Office navigation entry and New menu items.
- Add an Office Recent view backed initially by Office-tagged threads/projects.
- Preview current Office render manifests in the artifact panel.
- Show page/slide thumbnails, current source hash, preflight, and review status.
- Keep chat as the editing surface in this batch.

#### Implementation Checkpoint: Read-Only Office Projects

Implemented on 2026-07-17:

- `OfficeRevisionStore` now exposes bounded read surfaces for verified projects,
  canonical parent-chain history, immutable artifacts, and render-preview PNGs.
  Revision listing walks from the selected current revision and therefore does
  not promote an unpublished orphan directory after an interrupted pointer
  update.
- The user-scoped Gateway surface is available at
  `GET /api/office/projects`, `GET /api/office/projects/{project_id}`, and
  `GET /api/office/projects/{project_id}/revisions`. The canonical revision
  detail endpoint at
  `GET /api/office/projects/{project_id}/revisions/{revision_id}` returns exact
  revision metadata and render evidence without accepting unpublished orphan
  directories. Artifact and preview endpoints use the same canonical-chain
  boundary and recheck the recorded SHA-256 before serving bytes. Responses
  expose only display filenames and trusted evidence fields; host, source,
  output, and render-directory paths stay private.
- `/workspace/office` is a real Recent view with search, format filters, current
  revision state, source-hash prefix, and evidence-backed thumbnails. It does
  not infer Office projects from thread names or use placeholder project data.
- `/workspace/office/projects/{project_id}` combines current render windows by
  page number, preserves the newest evidence on overlap, and shows page
  thumbnails, full current SHA-256, package validation, preflight state, visual
  review state, semantic/package change counts, and canonical revision history.
- Canonical history rows are selectable. Historical save points use stable
  `/workspace/office/projects/{project_id}/revisions/{revision_id}` deep links,
  fetch their own revision detail and evidence, expose the selected artifact for
  download, and return to the current project URL without retaining stale
  preview state.
- The New menu routes presentation, document, and workbook outcomes into the
  built-in Office Agent with a typed starter. Existing project editing still
  returns to chat; OX2 adds no browser-side Office mutation surface.
- Desktop and 390-pixel mobile Playwright coverage verifies Recent, current and
  historical project preview, revision selection, selected SHA/artifact
  identity, page selection, starter routing, sidebar discovery, and horizontal
  bounds. The API suite also covers cross-user isolation, orphan-revision
  rejection, tampered-preview rejection, conditional PNG caching, and
  event-loop filesystem offloading.

OX2 is complete for read-only discovery and canonical revision preview.
Preflight remains `not_recorded` when the selected revision has no persisted
preflight evidence; the UI deliberately reports that state instead of deriving
one from package validation. Template, brand, project mutation, approval, and
unified cross-domain Recent work remain later batches.

#### OX2 Revalidation And Canonical Evidence Hardening

Revalidated on 2026-07-17 against the implementation rather than this audit
summary:

| Classification          | Scope                                                                                                                                                           | Decision                                                                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Already present         | User-scoped project, canonical revision, artifact, and render-preview reads; real Recent data; current and historical preview routes; search and format filters | Keep the existing API and UI boundaries.                                                                                                          |
| Required hardening      | Direct render-evidence reads and render-source verification could resolve a valid but unpublished revision directory outside the canonical parent chain         | Bind all render evidence to canonical revisions, ignore well-formed orphan evidence in project listings, and reject direct orphan preview access. |
| Not appropriate for OX2 | Browser-side Office mutation or inferred project records from chat titles                                                                                       | Keep chat as the editing surface for this read-only milestone.                                                                                    |
| Defer                   | Unified cross-domain Recent and broader project governance                                                                                                      | Handle through later product/runtime batches instead of widening this API.                                                                        |

`OfficeRevisionStore` now uses the verified canonical chain for both render
source binding and persisted evidence reads. Project evidence listings skip a
well-formed orphan left by an interrupted publication, so Recent remains
available, while exact evidence, preview, and revision routes fail closed. The
Gateway regression covers the full behavior through authenticated API routes.

Recent search/clear behavior and the 390-pixel Recent layout are now included
in the Office Playwright flow. The revalidation passed 428 Office backend tests,
470 frontend unit tests, the complete frontend lint/typecheck/build gates, and
four Office project Playwright scenarios on the system Chrome executable.

### OX3: PPTX Template Library V1

- Personal templates only.
- Import, validate, render, map, and publish immutable versions.
- Existing text and source-picture slots only.
- Fixed slide count and structure.
- Instantiate from exact bytes and reject every out-of-slot mutation.
- Add template cards, detail view, slot list, versions, and QA status.

#### Implementation Checkpoint: Trusted Personal PPTX Templates

Implemented on 2026-07-17:

- `OfficeTemplateStore` owns a user-scoped template catalog with immutable
  published snapshots. Import accepts a bounded native PPTX, rechecks its
  package and source SHA-256, persists complete inspection/preflight evidence,
  and derives text/picture candidates only from authored-ID object paths.
  Browser requests select server-issued candidate IDs; they cannot submit an
  arbitrary selector or expand the write surface.
- Draft mapping supports existing single-line text shapes and embedded source
  pictures only. Slot keys, types, required state, text length constraints,
  source fingerprints, allowed operations, fixed slide count, and the full
  object-structure fingerprint are validated again whenever a version is read.
  Every non-slot object remains locked.
- Full-deck template rendering uses bounded 12-slide windows, requires one
  consistent renderer pipeline, verifies every PNG and source-slide identity,
  and stores immutable evidence generations. Publication requires at least one
  mapped slot, complete render evidence, and an explicit review decision for
  the currently selected evidence. Published source, mapping, QA, and render
  bytes are immutable.
- The Gateway exposes personal template list/import/detail/version, mapping,
  render, review, publish, source-download, preview, and instantiate resources.
  Blocking package, filesystem, edit, and render work runs outside the event
  loop. Uploads are bounded, preview bytes are integrity-checked, and host paths
  are not returned.
- `/workspace/office/templates` is a real catalog with import and version-aware
  detail views. Owners can map candidates, render all slides, review the exact
  evidence, and publish only after the server gates pass. Desktop and 390-pixel
  mobile layouts were visually inspected from Playwright screenshots.
- `Use template` generates a typed form from the published slot schema. The
  browser submits only slot keys plus text values or indexed PNG/JPEG uploads.
  The backend starts from the exact published source bytes, applies only
  compiled text/picture operations, validates the result, runs preflight,
  verifies semantic receipt target paths, and rechecks the fixed object
  structure before committing a project.
- A template-created project stores the pinned template ID, version, and source
  SHA-256 on its immutable baseline and edit revisions. Its baseline artifact is
  byte-for-byte equal to the published template. The resulting revision stores
  template-policy evidence alongside the semantic change receipt and receives
  full-deck render evidence before the UI opens the project preview.
- Template locks continue after instantiation. `office_edit` resolves the
  current revision's template pin and rejects unsupported operation types,
  wrong slot types, out-of-slot paths, incomplete semantic evidence, structure
  drift, stale parents, attempts to remove/change the template version, and
  low-level revision commits that omit policy evidence.
- Focused verification covers exact-byte baselines, text and picture binding,
  optional and required slots, stale/unknown candidates, immutable publication,
  render batching, source/preview tamper rejection, cross-user isolation,
  event-loop offloading, template-to-project navigation, and the complete
  mapping-to-published-to-project browser flow.

OX3 is complete for the personal fixed-structure PPTX V1 boundary. Creating a
new version of an existing template, duplicate/archive actions, organization
permissions, brand profiles, repeatable slides/objects, charts/tables, and
project approval/restore remain later batches. Instantiated project renders
start in `pending`; visual acceptance of the generated result is not inferred
from the template's source review and belongs to the OX4 project workflow.

### OX4: Office Project And Save Points

- First-class project/revision records.
- Template-driven brief form plus chat.
- Semantic change panel and before/after render comparison.
- Restore by creating a new revision from an older source.
- Explicit current/final artifact selection.

#### OX4 Current-State Classification

| Classification   | Current evidence and decision                                                                                                                                                                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Already present  | User-scoped project records, immutable canonical revision chains, exact artifact SHA-256 checks, semantic receipts on edits, render evidence, historical deep links, template-generated forms, and chat routing are implemented.                                                        |
| Implement in OX4 | Immutable project visual-review decisions bound to exact revision and page evidence; receipt detail and parent/child render comparison; full-project render action; restore as a new optimistic-parent revision; and a separately selected final artifact backed by an approved review. |
| Not appropriate  | Rewinding the current pointer, mutating historical revision/render records, inferring approval from template review, silently reusing stale preview evidence, or adding a browser-native Office editor to this workflow.                                                                |
| Defer            | Organization approval roles, multi-reviewer quorum, template-version upgrades, brand governance, cross-domain project activity, and scheduled publication remain outside the personal Office Project V1 boundary.                                                                       |

The OX4 storage contract keeps `current` and `final` distinct. `current` advances
only by appending a verified revision. `final` is an explicit immutable
selection record that points to an approved canonical revision; selecting a
final artifact never rewrites revision history.

#### Implementation Checkpoint: Evidence-Bound Review And Restore

Implemented on 2026-07-17:

- The project workflow can render every page of an exact canonical DOCX, PPTX,
  or XLSX revision in bounded windows. A complete render set requires one source
  SHA-256, pipeline fingerprint, page count, exact page sequence, and, for
  presentations, exact source-slide identity across all evidence records.
  Conflicting or incomplete windows are not eligible for review.
- Visual-review decisions are immutable records bound to one revision and the
  exact complete render-evidence IDs. `approved` and `changes_requested` are
  explicit decisions; rerendering does not silently transfer an older decision
  to new evidence.
- Revision comparison uses the selected revision's canonical parent, semantic
  change receipt, and independently verified before/after render sets. The UI
  exposes page-by-page visual comparison plus source/result SHA-256, operation
  IDs, stable object paths, semantic deltas, coverage, and package/relationship
  counts without deriving change claims in the browser.
- Final selection is a separate immutable record. It requires the latest review
  for the selected revision to be approved and checks the caller's expected
  current revision before publication. Selecting or downloading a final
  artifact never moves the current pointer, and later edits or restores do not
  silently replace the chosen final artifact.
- Restore reads the exact bytes and resources of an older canonical revision,
  validates them again, builds a restore receipt, and appends a new revision
  with an optimistic current-parent check. It never rewinds or mutates history.
  Template-pinned projects additionally reapply the published slot allowlist
  and fixed-structure policy. Generic non-template restores report semantic
  coverage as `partial` while still recording exact artifact and package
  changes; they do not claim object-level evidence that was not evaluated.
- The Gateway now provides exact revision comparison, full render, immutable
  review, final selection/download, and append-only restore resources. Package,
  render, and filesystem work remains off the event loop, integrity failures
  are fail-closed, and host paths are not returned.
- The project page now has Preview, Compare, and Changes views plus compact
  render, visual-review, final, restore, and final-download actions. Revision
  history identifies current, final, baseline/edit/restore, and review state.
  Restore uses an explicit confirmation and returns to the newly appended
  current save point.
- Verification completed with 426 backend Office tests, 470 frontend unit
  tests, eight Office project/template Playwright tests, backend Ruff, frontend
  lint/typecheck, a production Next.js build, and desktop plus 390-pixel visual
  QA. Browser coverage exercises review-to-final-to-restore as one stateful
  workflow and confirms revision history remains append-only.

OX4 is complete for the personal project review/save-point boundary. It does
not add organization roles, review quorum, mutable approvals, browser-native
Office editing, or inferred acceptance. Those remain deferred to their
explicit product and authorization batches.

### OX5: Office Domain Agent Profile

- Add a built-in, non-deletable Office runtime profile through an Agent registry.
- Bind Office Studio runs to this profile.
- Add Agent origin/capability metadata to the gallery.
- Allow user Agents to reference permission-checked skills/templates/brands.
- Keep internal workers separate.

### OX6: Selection-To-Chat

- PPTX inspection-derived object overlays on native render previews.
- Typed selected-object context in chat requests.
- Targeted operation proposal and review.
- Later extend to DOCX structure and XLSX ranges when their views and write
  surfaces are mature.

#### OX6 Current-State Classification

| Classification   | Current evidence and decision                                                                                                                                                                                                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Already present  | OX2 provides user-scoped canonical project revisions and render evidence; the PPTX engine already returns stable authored-ID object paths, geometry, text, picture identity, and typed operation boundaries; OX4 provides immutable revision receipts and before/after evidence.                                                                       |
| Implement in OX6 | Derive a bounded one-slide selection surface from exact canonical bytes; carry only typed identity into Office chat; resolve it again at the Gateway; constrain `office_edit` and its receipt to the selected object; require one-time approval of the exact proposal; expose accessible preview overlays, an object list, and a persistent chat chip. |
| Not appropriate  | Trusting browser-authored object metadata, accepting raw host paths, selecting a historical revision for mutation, broad slide or presentation writes from an object selection, inferring approval from a chat message, or adding a browser-native Office editor.                                                                                      |
| Defer            | DOCX structural selection, XLSX range selection, grouped or multi-object transactions, slide-background selection, richer editor handles, organization policy, and delegated approval. These require their own typed views and authorization contracts.                                                                                                |

#### Implementation Checkpoint: Exact PPTX Object Review

Implemented on 2026-07-17:

- The read-only selection API at
  `GET /api/office/projects/{project_id}/revisions/{revision_id}/selection`
  derives one slide directly from the exact user-scoped canonical PPTX bytes.
  It returns the source SHA-256, slide dimensions, stable authored-ID paths,
  object fingerprints, bounded text previews, geometry overlays, selection
  status, and operation allowlists without exposing filesystem paths.
- The project preview renders selectable top-level objects as overlays and as an
  accessible object list. Historical revisions remain inspectable but cannot
  launch a mutation. The current revision routes an opaque typed identity into
  the built-in Office Agent; object names and document text are not placed in
  the URL.
- The Agent chat fetches the selection surface again and requires an exact
  project, revision, source hash, path, and fingerprint match before showing the
  context chip or sending a run. The selected object remains visible across the
  approval turn and can be explicitly cleared.
- The Gateway removes client attempts to set server-owned Office context, limits
  selections to the Office Agent, requires the current user-scoped PPTX
  revision, resolves the object from canonical bytes before creating the run,
  and injects only the verified result as request-scoped runtime context.
- The runtime supplies the verified object to the model as hidden current-turn
  context. In selected-object mode, `office_edit` requires `source_path: null`,
  reads the exact current project revision itself, rejects operations outside
  the selected path or allowlist, and verifies that the complete semantic
  receipt remains inside that scope before publishing output or a revision.
- A selected-object edit cannot execute on its proposal turn. The approval
  middleware hashes the exact selection identity and complete tool arguments,
  emits a structured review request, and ends the graph before mutation. Only a
  matching later approval can release that exact call; cancellation fails
  closed, argument changes require a new review, and oversized proposals must be
  split rather than shown with hidden truncation.
- Backend tests cover stale revisions, spoofed context, cross-user isolation,
  operation and receipt escapes, approval replay, changed arguments,
  cancellation, forged responses, review bounds, and synchronous/asynchronous
  middleware paths. Frontend unit and Playwright coverage exercises the real
  two-turn selection-to-review-to-approval flow. Desktop and 390-pixel visual QA
  confirms the complete review and both decisions remain usable above the
  composer without horizontal overflow.

Final revalidation passed 665 relevant backend tests, including all 459 Office
tests plus Gateway and agent-composition coverage; 474 frontend unit tests; all
five Office Project Playwright scenarios; frontend lint and typecheck; targeted
Ruff and Prettier checks; and the production Next.js build.

OX6 is complete for one current-revision PPTX object and the currently supported
typed object operations. It does not claim freeform canvas editing, arbitrary
object creation, multi-selection, DOCX/XLSX selection, or approval delegation.

### OX7: Editable Native Generation

- Add the versioned presentation-generation IR and deterministic layout
  compiler defined in the capability audit.
- Compile editable text, image, and simple shape objects.
- Allow templates and brand profiles to constrain the compiler.
- Require inspect, preflight, render, visual review, and PowerPoint/WPS corpus.

#### OX7 Current-State Classification

| Classification   | Current evidence and decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Already present  | The PPTX engine validates and inspects editable native objects, quality preflight is source-hash-bound, the renderer persists revision evidence, Office Projects provide review/final/restore, and the PowerPoint/WPS corpus proves the existing typed edit surface. `python-pptx` is available transitively, but the public generation skill currently creates one raster image per slide and therefore provides no editable object model.                                                                                                                                                                                    |
| Implement in OX7 | A VassilFlow-owned versioned presentation intent schema with stable slide/object IDs and no raw coordinates or OOXML; bounded theme tokens; deterministic semantic layouts, text fitting, contrast selection, image fitting, and authored object naming; native editable text, embedded image, and simple shape compilation; an exact generation receipt and persisted IR digest; a first-class `office_generate` tool that commits a generated project revision and runs package validation plus static preflight; project/API/UI evidence for generated revisions; and native round-trip fixtures for the generated surface. |
| Not appropriate  | Importing a generic scene graph or editor runtime, copying a reference schema, accepting arbitrary EMU coordinates or XML fragments from the model, treating browser rendering as Office fidelity authority, downloading web fonts at runtime, or relabeling raster-slide composition as native editable generation.                                                                                                                                                                                                                                                                                                           |
| Defer            | Native charts, tables, SmartArt, equations, audio/video, notes, transitions, animations, custom geometry, arbitrary master/layout import, interactive canvas editing, and realtime collaboration. Each requires its own typed contract, semantic receipt, native corpus, and visual evidence. Organization-managed brand/template catalogs remain OX8; OX7 will expose a bounded theme-constraint envelope that those trusted resources can compile into later.                                                                                                                                                                |

The V1 compiler will use semantic layout slots rather than a universal canvas:
title, title-and-content, two-column, picture-with-caption, and closing. Every
slide must carry a non-empty accessible title. Text and images are authored as
real PPTX objects; decoration is limited to compiler-owned simple shapes. The
same canonical IR must produce the same geometry, object order, object mapping,
and package payload bytes for a fixed compiler version and fixed image bytes.
The compiler may shrink text within a bounded type scale but must reject content
that cannot fit above the minimum readable size.

#### Implementation Checkpoint: Evidence-Bound Native Generation

Implemented and revalidated on 2026-07-17:

- `PresentationIntent` is a strict, versioned semantic schema. It accepts only
  stable slide/element IDs, five compiler-owned layouts, bounded theme tokens,
  text or bullets, local image references with alt text, and simple decorative
  shapes. Unknown fields, coordinates, raw OOXML, duplicate IDs, unsupported
  roles, unsafe images, and unreadable overflow fail closed.
- The deterministic compiler emits editable native title placeholders, text
  boxes, embedded pictures, and simple shapes. Fixed input and image bytes
  produce the same package bytes, object order, geometry, authored
  `VFGEN:<slide-id>:<element-id>` names, intent digest, and object-path mapping.
  Image `cover` and `contain`, text fitting, type scale, and contrast choices
  remain compiler-owned.
- `office_generate` validates and preflights the exact compiled package before
  publication. It commits a trusted initial `generation` revision whose
  evidence includes the full stored intent, artifact SHA-256, compiler ID and
  version, exact slide/object mapping, embedded asset digests, bounded counts,
  package validation, and complete static preflight. Evidence readback
  recomputes those records from canonical artifact bytes and rejects missing,
  cross-kind, malformed, truncated, or injected fields.
- Generated revisions have no invented parent comparison. A subsequent
  `office_edit` appends a normal child revision with its own semantic change
  receipt. Recent, project detail, history, and revision APIs expose bounded
  generation counts and evidence without source paths or raw intent payloads.
  Project listing reuses verified current-revision snapshots so the Recent API
  opens only selected artifacts instead of rereading every artifact twice.
- The Office UI identifies generated projects, displays compiler and intent/
  output identities, slide purposes and layouts, object paths, assets, static
  findings, and render/review state. Compare remains disabled for the initial
  revision while Changes shows generation evidence. Desktop, Recent, and
  390-pixel views were inspected from Playwright screenshots. A real mobile
  nested-scroll overlap found during that review was fixed and is now guarded
  by a geometry assertion.
- The public presentation skill now uses `office_generate` as its default and
  requires inspect, full render, page-by-page visual review, and exact revision
  evidence before delivery. The old one-image-per-slide script remains only as
  an explicit flattened fallback; it requires acknowledgement and reports
  `editable_objects: false`.
- `tests/fixtures/office/pptx/generation` is a separate generation corpus. Its
  byte-exact seed covers all five layouts, 15 native objects, bullet text,
  shapes, embedded PNG pictures, both image-fit modes, and alt text. Microsoft
  PowerPoint 16.0 build 20131 and WPS Presentation 12.1.0.26886 opened and saved
  that exact seed. Both retained all stable names, object paths, text, image
  ownership, and alt text, passed complete preflight, and accepted a subsequent
  exact-path edit that changed only `ppt/slides/slide1.xml`.
- The isolated LibreOffice/PDFium pipeline rendered all five pages of the seed
  and both native outputs at 120 DPI with pipeline fingerprint
  `763d712cc851eae742bb1ca69411d3fcb7fb3a143425e0e8e4638e514692c422`.
  PowerPoint output matched the seed page-for-page at the pixel hash level.
  WPS normalized the slide width from 1601 to 1600 render pixels; all five WPS
  pages were separately inspected and retained equivalent unclipped layout.

Verification passed 476 Office backend tests, 190 registry/config/Gateway
integration tests, three flattened-fallback skill tests, 474 frontend unit
tests, frontend lint and typecheck, a production Next.js build, and all ten
Office Project and Template Playwright scenarios. Targeted backend Ruff and
Office Prettier checks are clean. Full-repository Ruff still reports two
pre-existing import-order findings in `tests/test_threads_router.py`; full
Prettier reports five unrelated existing files. Neither set was modified.

OX7 is complete for the semantic native PPTX V1 boundary. It does not claim a
general slide scene graph, arbitrary slide mutation through `office_edit`,
charts/tables/SmartArt, notes or media timelines, custom masters, browser
canvas editing, or organization governance. Those remain gated by separate
typed contracts, native corpora, receipts, and authorization work.

### OX8: Organization Governance And Automation

- Organization template/brand/skill publishing and approval.
- Usage audit and version rollout controls.
- Workflows for scheduled or event-driven recurring Office generation.
- Explicit test run before activation.

Do not begin this batch until VassilFlow has a real organization membership and
authorization model. A filesystem `shared` directory is not sufficient.

#### Office V1 Closure Re-Audit

Re-audited against the implementation on 2026-07-17 after OX7 and the H1
geometry follow-up:

| Classification  | Direct code evidence and decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Already present | OX1-OX7 are represented by immutable Office Project revisions, semantic edit receipts, read-only Recent/project APIs, preview and review UI, trusted personal PPTX templates, exact selection-to-chat approval, the built-in Office Agent, and evidence-bound native PPTX generation. H1 now adds nested-group frame/PPI evidence and a dedicated PowerPoint/WPS corpus. `PresentationElement` deliberately contains text, image, and simple-shape variants; `PptxEditOperation` deliberately contains exact text, run, paragraph, shape, line, background, and picture-source operations. |
| Need port       | No additional reference capability qualifies for immediate inclusion inside Office V1. The next independent product batch must first choose one typed object family or establish organization authorization, then define its selector/intent, receipt snapshot, native corpus, render evidence, API/UI projection, and rollback behavior before implementation.                                                                                                                                                                                                                            |
| Not appropriate | Importing a browser scene graph, generic brand linter, canvas editor runtime, raw OOXML mutation, generic overlap repair, or filesystem-only shared catalog would bypass VassilFlow's package-preserving engine, evidence model, and authorization boundary. The inspected brand-lint reference assumes a semantic node graph plus an approved brand kit; VassilFlow currently has neither an organization policy authority nor a safe basis for automatic color/font replacement.                                                                                                         |
| Defer           | Native table/chart/SmartArt generation or mutation, arrange/z-order commands, theme/master/layout mutation, notes/media timelines, effects/3D/custom geometry, DOCX/XLSX generation IR, organization publishing/approval, and scheduled generation. The current code has inspect-only identities for several of these families but no corresponding typed mutation union. No organization membership or product scheduler exists in the backend, so OX8 remains blocked by architecture rather than implementation effort.                                                                 |

This closes the independently testable Office V1 boundary. "Complete" here
means the documented typed surfaces, project workflow, generation compiler,
quality evidence, and visual-review path are production-testable together. It
does not relabel deferred Microsoft Office feature families as implemented.

## First Vertical Slice

The smallest end-to-end slice that validates the product direction is:

1. Import a fixed-structure corporate PPTX.
2. Render and preview all slides.
3. Mark two text shapes and one picture as variable slots.
4. Publish template version 1 bound to its source SHA-256.
5. Start a project from that template.
6. Fill required values through a generated form or chat.
7. Apply only exact text/picture operations to a byte-for-byte clone.
8. Reject changes outside the slot allowlist.
9. Show semantic change receipt and before/after renders.
10. Complete visual review and export an editable PPTX.
11. Reopen the result in Microsoft PowerPoint and WPS corpus lanes.

This slice uses capabilities VassilFlow already has or has explicitly planned,
and tests the real value of company-template reuse without requiring a full
browser Office editor.

## Success Criteria

- A first-time user can discover Office without knowing tool or skill names.
- A chat-first user can still request Office work from the default lead Agent.
- The same project opens from chat, Recent, or template history.
- A template owner can see and control every variable region.
- A generated file proves which template/brand versions and input bindings it
  used.
- Locked content cannot change even when the model proposes it.
- Every change has a semantic receipt, package validation, render evidence, and
  honest visual-review state.
- Agent cards represent meaningful roles, not every file format or internal
  worker.
- Templates, skills, brand resources, Agents, and projects remain independently
  versioned and permissioned.

## Verification Notes

- This research read current VassilFlow backend and frontend code directly.
- External product conclusions use current official help/support sources rather
  than copied UI or third-party summaries.
- Official reference screenshots were viewed from ignored `research/` storage
  and are not added to the repository.
- This document changes no runtime, frontend, configuration, local Office file,
  or secret.

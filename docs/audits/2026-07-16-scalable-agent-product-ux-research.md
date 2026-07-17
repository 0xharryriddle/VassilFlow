# VassilFlow Scalable Agent Product And UX Research

Date: 2026-07-16
Status: Product architecture and interaction recommendation

## Scope

This research extends the Office product audit to answer a broader question:
how should VassilFlow remain understandable when it offers ten or more
functional Agents, each with different tools, work products, data access, and
interaction surfaces?

The recommendation is grounded in:

- Current VassilFlow frontend and backend code
- Current official product documentation for several Agent platforms
- The Office capability and product audits already completed in this repository
- The requirement that VassilFlow remain an independent super-agent harness

External products are product references only. Their names, UI copy, visual
identity, schemas, and implementation details must not enter public VassilFlow
surfaces.

## Executive Decision

Adding an Agent must not add another permanent item to the primary sidebar.

VassilFlow should use a stable semantic shell:

1. Home
2. Chats
3. Projects
4. Agents
5. Activity

Users discover all Agents in the Agent Catalog, pin a small personal subset,
launch common outcomes from a single New menu, and see the active Agent in the
project or conversation header.

Office remains a first-class domain experience, but it becomes one instance of
a scalable pattern rather than a one-off permanent navigation exception.

This intentionally refines the narrower sidebar proposal in
`2026-07-16-office-product-agent-ux-research.md`. The earlier decision that
Office needs a real workspace still stands; only its global navigation policy
changes once VassilFlow plans for many peer domains.

The product model is:

- **Agent Catalog** answers who can do the work.
- **New menu** answers what the user wants to start.
- **Project** holds durable work and artifacts.
- **Chat** holds a conversation.
- **Activity** shows what all Agents are doing or waiting for.
- **Pinned Agents** provide personal shortcuts without defining global IA.

This shell does not change when the eleventh or fiftieth Agent is added.

## Current VassilFlow Evidence

### Existing Strengths

The current frontend already provides reusable foundations:

- A collapsible workspace sidebar in
  `frontend/src/components/workspace/workspace-sidebar.tsx`
- A simple primary navigation group in
  `frontend/src/components/workspace/workspace-nav-chat-list.tsx`
- A searchable-command component foundation in
  `frontend/src/components/workspace/command-palette.tsx`
- A dedicated Agent gallery and reusable cards under
  `frontend/src/components/workspace/agents/`
- Separate chat routes for the lead Agent and custom Agents
- Thread-scoped artifacts, uploads, workspace state, and outputs
- An Agent runtime configuration that already bounds models, tool groups,
  skills, memory, and SOUL instructions

These parts should evolve rather than be replaced wholesale.

### Current Scaling Limits

The current implementation assumes an Agent is a specialized chat:

- The sidebar has only Chats and Agents.
- Every Agent card opens `/workspace/agents/{agent_name}/chats/new`.
- `Agent` metadata contains only name, description, model, tool groups, skills,
  and optional SOUL content.
- The gallery does not distinguish built-in, personal, team, verified, or
  project-backed Agents.
- There is no favorite or pin state.
- There is no Agent category, launch mode, project kind, activity summary,
  permission summary, or last-used state.
- The command palette exposes New Chat, settings, and keyboard shortcuts, but
  cannot search Agents, projects, or creation outcomes.
- Recent navigation is a thread list, not a unified recent-work model.

These are reasonable constraints for the current product, but directly listing
ten Agents in the sidebar or treating all ten as chat routes would make the
next architecture accidental.

### Backend Registry Limit

`AgentConfig` in
`backend/packages/harness/vassilflow/config/agents_config.py` is a custom-Agent
runtime config, not yet a product catalog manifest.

It correctly controls runtime behavior, but the product needs additional
metadata that should not be inferred by the frontend from names:

- Stable ID and display name
- Origin: built-in, personal, or team
- Category and keywords
- Launch mode: chat or project
- Project/workspace kind when project-backed
- Icon key from the VassilFlow icon set
- Visibility and lifecycle status
- Capability and data-access summary
- Suggested starters and supported input/output types
- Verification or approval state when organization governance exists

The runtime config and product manifest can share an identity, but they are not
the same responsibility.

## Product Research

### Genspark

Official references:

- https://www.genspark.ai/helpcenter/custom-super-agent
- https://www.genspark.ai/helpcenter/skills
- https://www.genspark.ai/helpcenter/hub
- https://www.genspark.ai/helpcenter/ai-slides

Observed patterns:

- A central Agent store provides My Agents, favorites, official Agents,
  trending Agents, categories, and search-oriented discovery.
- Favorite Agents remain easy to invoke without keeping the whole catalog in
  navigation.
- An Agent can be invoked from a general conversation with `@`.
- Domain products such as Slides remain separate working surfaces rather than
  being reduced to Agent cards.
- Skills and persistent project context are separate product concepts.

VassilFlow lesson:

- Catalog, invocation, skill reuse, and domain workspace are complementary
  layers.
- `@Agent` is useful only after a unified Agent registry and delegation
  contract exist. A frontend-only mention parser would create false semantics.

### Microsoft 365 Copilot

Official references:

- https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-agent-store
- https://learn.microsoft.com/en-us/microsoft-365/admin/manage/agent-registry

Observed patterns:

- Agent Store is the central catalog.
- Agent details expose publisher, users, data and tools, security, compliance,
  certification, and activity.
- Users and administrators can pin Agents instead of placing all available
  Agents in permanent navigation.
- Administrator pinning is deliberately limited and ranked.
- Built-in, organization-built, and external Agents have explicit origins and
  governance paths.

VassilFlow lesson:

- Pinning is a scarce personalization mechanism, not a second catalog.
- The Agent profile must expose capability and access boundaries before
  organization sharing is added.
- Origin and lifecycle must become first-class metadata before VassilFlow mixes
  built-in and user-defined Agents in one gallery.

### Atlassian Rovo

Official references:

- https://support.atlassian.com/rovo/docs/browse-agents/
- https://support.atlassian.com/rovo/docs/agents/
- https://support.atlassian.com/rovo/docs/agent-actions/

Observed patterns:

- Agents can be found from Chat, contextual editors, automation, and a Studio
  management surface.
- The catalog supports search, Favorites, and My Agents.
- Agent profiles show creator, instructions, knowledge sources, tools, and
  conversation starters.
- Contextual invocation lets an Agent act near the object being edited.
- Tool actions require confirmation and respect the invoking user's
  permissions.

VassilFlow lesson:

- The same Agent may have multiple entry points, but should keep one identity
  and one permission contract.
- Contextual invocation is more valuable than adding more global navigation.
- Agent profiles should describe actual access and tools, not only personality.

### Notion

Official references:

- https://www.notion.com/help/notion-agent
- https://www.notion.com/help/custom-agents
- https://www.notion.com/help/best-practices-for-creating-and-optimizing-a-custom-agent

Observed patterns:

- The general Agent receives current-page or selected-block context.
- Shared custom Agents may appear in an Agents section and search results.
- A maintained Agent separates Chat, Activity, and Settings.
- Custom Agents are recommended for recurring work; one-time asks remain with
  the general Agent.
- Data access, web access, tools, triggers, model, versions, and sharing are
  independently managed.

VassilFlow lesson:

- Do not force a user to choose a specialized Agent for every one-time task.
- A durable custom Agent needs activity and configuration views in addition to
  chat.
- Current selection and project context should be attached structurally, not
  reconstructed from prose.

### Zapier Agents

Official references:

- https://help.zapier.com/hc/en-us/articles/33336184962573-Review-your-agent-s-activity
- https://help.zapier.com/hc/en-us/articles/36713413544845-Big-changes-to-Zapier-Agents-and-planned-maintenance

Observed patterns:

- All-Agent activity and per-Agent activity are separate views.
- Related automation Agents can be grouped for operational oversight.
- Agent status and runs become more important than chat when work executes in
  the background.

VassilFlow lesson:

- Activity must be a cross-Agent product surface before scheduled or
  event-driven Agents are introduced.
- Grouping autonomous workers is an operations concern and should not be
  confused with the current internal subagent registry.

## Cross-Product Synthesis

The strongest recurring patterns are:

1. **Catalog for breadth**: search, categories, origin, details, and discovery.
2. **Pins for frequency**: only a small personal set remains immediately
   visible.
3. **Context for relevance**: invoke the Agent from the current page, project,
   selection, or object.
4. **Projects for durability**: files, revisions, templates, state, and
   approvals outlive a chat.
5. **Activity for trust**: running, waiting, completed, failed, and approval
   states are visible across Agents.
6. **Profiles for safety**: tools, data access, origin, and ownership are shown
   before sharing or automation.
7. **General Agent for one-time work**: specialization is optional until it
   provides repeatability, context, or a better working surface.

No examined product successfully scales by permanently listing every Agent as
a primary application section.

## VassilFlow Product Vocabulary

The UI and code should preserve these distinctions:

| Concept | Product meaning |
| --- | --- |
| Lead Agent | General conversational coordinator for one-time and cross-domain work |
| Domain Agent | Curated runtime profile for a product domain such as Office, Research, Code, or Data |
| Role Agent | User or team specialist for a repeatable professional outcome |
| Tool | Bounded atomic action with an explicit permission surface |
| Skill | Reusable method or playbook an Agent may apply |
| Worker | Hidden internal delegated runtime, never a catalog item by default |
| Project | Durable work container with files, revisions, conversations, and provenance |
| Run | One execution record with status, actions, approvals, and outputs |
| Workflow | Triggered or scheduled automation that invokes an Agent later |
| Experience | The UI surface used for a domain; an Agent may power it but is not the surface itself |

An Agent is an actor. A Project is the durable object being worked on. An
Experience is the interface. Keeping those three separate is the central
scaling rule.

## Recommended Global Information Architecture

### Fixed Sidebar

The stable sidebar should contain:

- **New**: one outcome-oriented creation menu
- **Home**: recent work, waiting approvals, and recommended continuations
- **Chats**: conversations across the lead and specialized Agents
- **Projects**: durable Office, Research, Code, Data, Design, and future work
- **Agents**: catalog, pinned Agents, personal Agents, and management
- **Activity**: all running, waiting, completed, and failed runs

Settings remains in the footer.

This is five semantic destinations, not ten feature destinations.

### Pinned Section

Below the fixed destinations, users may pin up to five Agents or domain
experiences. The first product version should show four before an overflow
entry.

Rules:

- Pin state is personal.
- Built-in Agents are not automatically pinned merely because they exist.
- An administrator may recommend Agents later, but organization pinning must
  wait for real organization membership and authorization.
- Pinned order is user-controlled.
- Adding Agent eleven never modifies the sidebar until the user pins it.

Example pinned set:

- Office
- Research
- Code
- Data

### Recent Work

Show at most five recent work items, not a complete history tree. Each item has
a type icon and opens the owning Project or Chat.

The current `RecentChatList` should not be generalized by putting project IDs
into thread rows. A small unified recent-work query can reference separate
resource types.

### Global New Menu

The New menu should be outcome-oriented:

- Chat
- Presentation
- Document
- Spreadsheet
- Research project
- Code task
- Data analysis
- More

It should show a limited recommended set based on availability and recent use.
It must not expand into a raw list of every Agent.

### Command Palette

The current command palette should eventually search across:

- Actions
- Agents
- Projects
- Chats
- Templates

This becomes the keyboard path for breadth while the sidebar remains compact.

## Ten-Agent Portfolio Example

The following portfolio illustrates how ten capabilities fit without ten
sidebar entries. Names are working VassilFlow-native examples, not committed
public product names.

| Agent | Kind | Default launch | Durable object | Typical discovery |
| --- | --- | --- | --- | --- |
| Office | Domain | Project | Office project | New menu, Catalog, pin |
| Research | Domain | Project | Research project | New menu, Catalog, pin |
| Code | Domain | Project | Code workspace/project | New menu, Catalog, pin |
| Data | Domain | Project | Dataset analysis project | New menu, Catalog, pin |
| Design | Domain | Project | Design project | Catalog, context |
| Knowledge Curator | Role | Chat or project | Knowledge collection | Catalog, project context |
| Sales Proposal | Role | Project | Proposal project | Catalog, template context |
| Support Analyst | Role | Chat | Conversation/case | Catalog, contextual launch |
| Campaign Planner | Role | Project | Campaign project | Catalog, project context |
| Meeting Follow-up | Role | Chat or workflow | Meeting record/run | New menu, Catalog, later trigger |

The Catalog shows all ten. The sidebar shows only the user's four or five
pins. The New menu shows only common outcomes. Project headers show which Agent
is currently responsible.

## Agent Catalog

### Catalog Structure

Use one page with:

- Search
- Origin tabs: All, Built-in, Yours, Shared
- One category filter
- Pinned section when non-empty
- Compact responsive grid for all matching Agents

Do not create a separate page for each category.

### Agent Card

Each card should show only:

- Icon
- Display name
- One-line outcome description
- Origin
- Launch type indicator: Chat or Project
- Pin icon
- Primary Open/Start action

Model names, every skill, and every tool group currently make cards noisy. Move
those details into the Agent profile.

### Agent Profile

Selecting an Agent opens a profile or detail route with:

- Outcome and example starters
- Built-in, personal, or team origin
- Chat/project launch behavior
- Tools and actions
- Data and knowledge access
- Enabled skills
- Model policy, when the user is allowed to see or change it
- Owner and sharing
- Version and update time
- Recent projects/conversations
- Recent activity

For user-maintained Agents, use tabs:

- Overview
- Conversations or Projects
- Activity
- Settings

The current delete action should remain unavailable for built-in Agents.

## Invocation Model

### 1. Intent Routing From Lead Chat

The user asks normally. The lead Agent may continue itself or propose opening a
domain Project. The transition must be visible:

1. Identify durable domain work.
2. Show the proposed Project type and primary Agent.
3. Create the Project after user confirmation when mutation or cost warrants
   it.
4. Continue the same intent in the project context.

### 2. Manual Agent Selection

The chat header contains the active Agent switcher. Starting a new conversation
from an Agent profile preselects that Agent.

Switching the primary Agent mid-thread should not silently reinterpret prior
state. The backend should either start a branch/new conversation or record an
explicit Agent transition event.

### 3. Project-Bound Agent

A Project has one primary Agent profile and may invoke hidden workers. Users
interact with the Project surface, not with each worker.

Office therefore opens preview, revisions, templates, chat, and QA. Code opens
repository/files, terminal activity, diffs, and chat. Data opens tables,
charts, lineage, and chat. They share shell behavior but not a forced generic
canvas.

### 4. Contextual Invocation

From a selection, object, file, slide, range, or code diff, the user chooses an
available Agent or asks the current one. VassilFlow attaches typed context and
permission scope to the request.

This is the preferred way to expose specialization inside domain workspaces.

### 5. `@Agent` Delegation

Defer public `@Agent` invocation until:

- User Agents and built-in domain Agents share a registry contract.
- Internal workers are clearly separated from invokable Agents.
- The backend validates the requested Agent and permission scope.
- The event stream can attribute delegated work and results.
- Thread/project provenance records the delegation.

When implemented, `@Agent` is temporary delegation. It does not change the
Project's primary Agent unless the user explicitly requests that change.

### 6. Background Invocation

Scheduled/event invocation belongs to Workflows and Activity. Do not put
triggers into the first interactive Agent catalog release.

## Domain Workspace Pattern

Every project-backed domain experience should share a shell contract:

- Project title and status
- Primary Agent switcher
- Project context and source identity
- Conversation/activity panel
- Revision or checkpoint access
- Change review
- Outputs and export/publish actions

The central working surface is domain-specific:

- Office: slide/page/sheet structure and render preview
- Research: source set, notes, evidence, and report
- Code: files, diffs, terminal/run evidence
- Data: table/grid, transformations, charts, and lineage
- Design: canvas/assets/variants and review

Shared shell does not mean forcing every domain into the Office UI.

## Home And Activity

### Home

Home is an operational dashboard, not a marketing landing page. It shows:

- Continue recent work
- Runs waiting for approval or clarification
- Pinned Agents
- Common New actions
- Recent outputs

No oversized hero or feature-description panels are needed.

### Activity

Activity aggregates runs across Agents and Projects:

- Running
- Waiting for input
- Waiting for approval
- Completed
- Failed
- Cancelled

Each row shows Agent, Project/Chat, trigger, start time, current step, and the
next available action. Internal worker details are nested under the owning run,
not listed as peer Agents.

## Responsive Behavior

### Desktop

- Full semantic sidebar
- Catalog in a two-to-four-column responsive grid
- Optional Agent profile drawer or detail route
- Domain Projects may collapse the sidebar to maximize the working surface

### Tablet

- Icon sidebar
- Two-column catalog
- Project conversation panel becomes a drawer

### Mobile

- Bottom navigation: Home, Chats, Projects, Agents
- Center Create action
- Activity in the top bar with a visible waiting count
- Domain Project tabs such as Preview, Chat, and Changes
- No ten-Agent horizontal carousel as the primary discovery mechanism

## Product Manifest Recommendation

Do not add all product metadata directly to the current user-authored
`config.yaml` without a migration contract. Introduce a typed manifest or API
projection that combines runtime and product metadata.

Conceptual shape:

```yaml
id: office
display_name: Office
origin: builtin
category: create
launch:
  kind: project
  project_kind: office
capabilities:
  - presentation
  - document
  - spreadsheet
visibility: available
icon: files
runtime:
  agent_name: office
```

The exact schema should be designed with migrations and tests. The UI must
receive server-authoritative launch and access data instead of hard-coding
routes by Agent name.

## Project Relationship

An Agent must not own files solely through a thread directory once Projects are
introduced.

Recommended relationships:

- Project has a stable project ID and project kind.
- Project points to its primary Agent ID.
- Project may have multiple conversations.
- Conversation points to a thread ID.
- Revision/checkpoint points to immutable source and outputs.
- Run points to Project, Conversation, Agent, and any internal worker spans.
- Recent Work references either a Project or a standalone Chat.

This allows the same Office project to be reopened from Home, Projects,
Templates, Chat history, or Agent profile without duplicating its state.

## Classification For VassilFlow

### Already Present

- Collapsible workspace sidebar
- Generic and Agent-specific chat routes
- Agent gallery and cards
- Per-user custom Agent storage
- Runtime model/tool/skill bounds
- Thread metadata and history
- Command palette foundation
- Thread-scoped artifact and workspace isolation

### Needs Evolution

- Stable semantic navigation
- Agent product manifest and origin metadata
- Catalog search, filters, pins, and launch types
- Unified New menu
- Project entity and recent-work projection
- Cross-Agent Activity
- Agent profile with capability/access detail
- Domain workspace shell contract
- Explicit Agent transition and delegation events
- Command palette search across Agents and Projects

### Not Appropriate

- One permanent sidebar destination per Agent
- Word, Excel, and PowerPoint as three Agents
- Showing internal subagents in the public Agent catalog
- Frontend-only `@Agent` routing
- Treating templates or tools as Agents
- Treating every one-time prompt as a reason to create an Agent
- Reusing thread storage as the complete Project model
- Hard-coding launch routes from Agent display names

### Defer

- Public Agent marketplace
- Organization-wide deployment and mandatory pins
- Agent verification/certification UI
- Scheduled/event Workflows
- Multi-Agent choreography editor
- Agent groups/pods for operations
- Organization analytics and chargeback

These require organization identity, authorization, audit, and lifecycle
foundations that VassilFlow does not yet expose as a mature product contract.

## Delivery Sequence

### AX1: Registry And Taxonomy

- Define built-in, personal, and future team Agent origins.
- Add stable IDs, launch type, category, icon key, and lifecycle metadata.
- Keep existing runtime fields intact.
- Add backend and frontend contract tests.

### AX2: Scalable Catalog

- Add search, origin tabs, category filter, and personal pins.
- Simplify cards and add Agent profiles.
- Preserve the current custom-Agent creation and chat path.

### AX3: Semantic Shell

- Add Home, Projects, and Activity destinations behind honest available states.
- Replace the single-purpose New Chat entry with a New menu.
- Expand command palette search.
- Keep sidebar pinned content bounded.

### AX4: Project Foundation

- Add Project, Conversation, Revision, and Run relationships.
- Add unified Recent Work without merging resource identities.
- Add project-bound Agent metadata and permission checks.

### AX5: Office As First Domain Experience

- Implement the Office batches defined in the Office product audit.
- Validate the shared domain shell with real render, revision, template, and QA
  state.

### AX6: Second Domain Validation

- Add either Research or Code using the same shell contract.
- Confirm that shared navigation and Project APIs work without forcing Office
  concepts into the second domain.

### AX7: Contextual Invocation

- Add typed selection/project context.
- Add server-validated Agent switch/delegation events.
- Add `@Agent` only after those contracts are stable.

### AX8: Background Operations

- Add Activity depth, approvals, triggers, and Workflows.
- Add organization governance only with real authorization support.

## First Implementable UX Slice

The smallest useful slice is not ten working Agents. It is proving that the UI
does not need to change when ten are registered:

1. Add product manifest metadata for the lead Agent, Office, Research, Code,
   Data, and Design fixtures.
2. Render them with the existing custom Agents in one catalog.
3. Search and filter by origin/category.
4. Pin up to four in the sidebar.
5. Launch chat-backed Agents through the existing route.
6. Show project-backed Agents as unavailable or route only Office when its
   Project foundation exists.
7. Verify desktop, collapsed sidebar, and mobile layouts.

This slice separates discovery and navigation work from pretending all domain
surfaces already exist.

## UX Acceptance Criteria

- Adding Agent eleven requires no fixed-navigation code change.
- Every available Agent is discoverable in at most two navigation actions.
- The sidebar shows no more than five personal Agent/domain shortcuts.
- Agent cards identify origin and Chat/Project launch type.
- Current Agent and Project are always visible during work.
- The user can inspect tools and data access before first use.
- One-time work remains possible through the lead Agent.
- Durable work can be reopened without finding its original chat message.
- Background work is visible in Activity and never masquerades as a normal chat
  response.
- Internal workers never appear as peer user-facing Agents.
- Mobile navigation does not become a horizontal list of Agent icons.

## Verification Notes

- Current VassilFlow sidebar, Agent gallery/card, command palette, Agent API,
  Agent config, and thread/runtime integration were read directly.
- Product conclusions use current official documentation rather than UI guesses
  or third-party summaries.
- This document is an internal audit and may name external reference products
  for technical traceability.
- No runtime, frontend, configuration, local Office file, or secret is modified
  by this research.

## Implementation Checkpoint: AX1 And Initial AX2

Implemented on 2026-07-16:

- Added product-facing metadata for real personal Agents without changing their
  runtime `AgentConfig` contract.
- Added stable catalog IDs, origin, category, icon key, availability, typed
  launch metadata, and management permissions to the gateway response.
- Added rolling frontend compatibility for gateway responses that predate the
  product metadata contract.
- Upgraded the existing Agent gallery with capability search, origin filtering
  when multiple origins exist, bounded per-user local pins, compact cards, and
  typed Chat/Project launch presentation.
- Verified backend contracts, frontend unit coverage, desktop browser behavior,
  and a 390 px mobile viewport with no horizontal overflow.

Intentionally not implemented in this checkpoint:

- Built-in domain fixtures without real runtime registrations or launch routes.
- Category filters, Agent profile pages, or sidebar pin projection.
- Project-backed Agents, project persistence, or Office-specific navigation.
- Team synchronization for pins; pins currently remain browser-local and are
  namespaced by user ID.

The next batch should establish a real built-in Agent registry before exposing
domain Agents in the catalog. That registry must only advertise launchable
capabilities and must not derive routes from display names.

## Implementation Checkpoint: Built-In Registry And Catalog Projection

Implemented on 2026-07-16:

- Added a server-owned built-in Agent registry whose runtime contract is
  independent from user-authored Agent files.
- Separated the read-safe product catalog from privileged custom-Agent prompt
  management, so built-ins remain discoverable under the secure default
  configuration without exposing personal Agent config or SOUL content.
- Registered Office only after verifying its three structured tools are
  configured inside the assigned runtime groups, load successfully, and expose
  the expected runtime names.
- Routed Office through the existing lead-agent graph and real Agent chat route,
  with a dedicated system identity, no mutable custom-Agent surface, and
  fail-closed launch behavior when required tools are absent.
- Added typed category filtering and a responsive Agent profile sheet exposing
  origin, launch mode, model policy, exact required tools, tool groups, skills,
  thread data access, starter prompts, and missing requirements.
- Projected the same bounded, per-user browser pins into the workspace sidebar
  without adding permanent navigation entries for each registered Agent.
- Verified backend contracts and runtime policy, frontend unit/type/lint checks,
  browser launch behavior, and expanded, collapsed, and mobile catalog/profile
  layouts.

Intentionally deferred:

- Durable Office Projects, project persistence, template libraries, and a
  project-backed Office launch route.
- Server-synchronized personal pins, team Agents, organization recommendations,
  and mandatory pins.
- Separate domain workbenches and cross-Agent delegation or `@Agent` routing.
- Advertising additional built-in Agents before each has an implemented runtime
  capability and honest launch destination.

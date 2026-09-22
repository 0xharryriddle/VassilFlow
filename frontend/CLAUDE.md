# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VassilFlow Frontend is a Next.js 16 web interface for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2

## Commands

| Command            | Purpose                                           |
| ------------------ | ------------------------------------------------- |
| `pnpm dev`         | Dev server with Turbopack (http://localhost:3000) |
| `pnpm dev:webpack` | Dev server with webpack                           |
| `pnpm build`       | Production build                                  |
| `pnpm check`       | Lint + type check (run before committing)         |
| `pnpm lint`        | ESLint only                                       |
| `pnpm lint:fix`    | ESLint with auto-fix                              |
| `pnpm test`        | Run unit tests with Rstest                        |
| `pnpm test:e2e`    | Run E2E tests with Playwright (Chromium)          |
| `pnpm typecheck`   | TypeScript type check (`tsc --noEmit`)            |
| `pnpm start`       | Start production server                           |

Unit tests live under `tests/unit/` and mirror the `src/` layout (e.g., `tests/unit/core/api/stream-mode.test.ts` tests `src/core/api/stream-mode.ts`). Powered by Rstest; import source modules via the `@/` path alias.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`.

## Architecture

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code) and **todos**.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes: `/` (landing), `/workspace/chats/[thread_id]` (chat).
- **`components/`** — React components split into:
  - `ui/` — Shadcn UI primitives (auto-generated, ESLint-ignored)
  - `ai-elements/` — Vercel AI SDK elements (auto-generated, ESLint-ignored)
  - `workspace/` — Chat page components (messages, artifacts, settings)
  - `landing/` — Landing page sections
- **`core/`** — Business logic, the heart of the app:
  - `threads/` — Thread creation, streaming, state management (hooks + types)
  - `api/` — LangGraph client singleton
  - `artifacts/` — Artifact loading and caching
  - `channels/` — IM channel connections (provider catalog, connect/runtime-config API + hooks)
  - `i18n/` — Internationalization (en-US, zh-CN)
  - `settings/` — User preferences in localStorage
  - `memory/` — Persistent user memory system
  - `skills/` — Skills installation and management
  - `messages/` — Message processing and transformation
  - `mcp/` — Model Context Protocol integration
  - `models/` — TypeScript types and data models
- **`hooks/`** — Shared React hooks
- **`lib/`** — Utilities (`cn()` from clsx + tailwind-merge)
- **`server/`** — Server-side code (better-auth, not yet active)
- **`styles/`** — Global CSS with Tailwind v4 `@import` syntax and CSS variables for theming

### Data Flow

1. User input → thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos)
3. TanStack Query manages server state; localStorage stores user settings
4. Components subscribe to thread state and render updates

Failed submissions keep the unpersisted human message and uploaded-file metadata
in the current page session. `ThreadChatPage` shows fixed localized error copy
and restores the input for manual editing and resubmission; it does not replay
runs automatically. Checkpoint reconciliation still replaces optimistic input.

The composer displays the reasoning effort derived from the active mode when no
explicit preference is saved. `MessageReasoning` keeps completed timing stable
and owns expansion state across the measured/unmeasured duration transition.
Keep these adapters outside the generated `ai-elements` components.

Dialog consumers must provide an appropriate localized `DialogDescription` or
`SheetDescription` connected to the content. Model selection, memory editing,
chat renaming, mobile navigation, and settings do this at their call sites;
keep generated `ui` and `ai-elements` wrappers unchanged.

Infinite chat queries store pages as `{ threads, nextOffset }`. The offset counts
raw backend rows (including hidden sidecars); cache rename/delete/upsert helpers
must preserve it, with `null` marking a terminal page. Do not infer a cursor from
the number of visible rows or attach metadata to arrays: TanStack structural
sharing can discard array metadata.

Run-history failures retain loaded messages and offer **Retry history** in main
and sidecar chats. HTTP/schema/cursor failures are not empty terminal pages;
changing threads aborts the old page request and discards stale completions.

### Key Patterns

- **Server Components by default**, `"use client"` only for interactive components
- **Thread hooks** (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API interface
- **LangGraph client** is a singleton obtained via `getAPIClient()` in `core/api/`
- **Environment validation** uses `@t3-oss/env-nextjs` with Zod schemas (`src/env.js`). Skip with `SKIP_ENV_VALIDATION=1`

Agent routes share `components/workspace/chats/thread-chat-page.tsx` and read
product metadata from `/api/agent-catalog`. The domain extension registry and
`agent-chat-extensions.json` manifest are currently empty; keep their keys in
sync when adding future extensions. Generic capability inputs and action
provenance remain in `core/capabilities` and `core/actions`. Attachment support
for DOCX, XLSX, and PPTX is independent of domain-specific workspaces.

## Code Style

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

## Environment

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:8001/api
```

Leave these unset for the standard `make dev` / Docker flow, where nginx serves
the public `/api/langgraph/*` prefix and rewrites it to Gateway's native `/api/*`
routes.

The SDK defaults to `credentials: "include"` only for its configured backend
origin and API path, retaining explicit credential policies and CSRF headers.
Like REST requests, state-changing SDK requests read the current CSRF cookie.
This supports a separate frontend/backend port on the same hostname when CORS
allows that frontend origin. The gateway's host-only cookies and strict CSRF
cookie do not support unrelated hostnames automatically; use the same-origin
proxy for that deployment. Credential inclusion does not override browser cookie
scope or SameSite rules.

Requires Node.js 22+ and pnpm 10.26.2+.

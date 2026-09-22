# VassilFlow Frontend

VassilFlow keeps the original minimal, easy-to-use web interface direction while moving the product surface toward a modern super agent harness.

For a fresh clone or full-stack setup, start with the repository-level guide:
[../docs/SETUP.md](../docs/SETUP.md). This README is for frontend-only work.

## Tech Stack

- **Framework**: [Next.js 16](https://nextjs.org/) with [App Router](https://nextjs.org/docs/app)
- **UI**: [React 19](https://react.dev/), [Tailwind CSS 4](https://tailwindcss.com/), [Shadcn UI](https://ui.shadcn.com/), [MagicUI](https://magicui.design/) and [React Bits](https://reactbits.dev/)
- **AI Integration**: [LangGraph SDK](https://www.npmjs.com/package/@langchain/langgraph-sdk) and [Vercel AI Elements](https://vercel.com/ai-sdk/ai-elements)

## Quick Start

### Prerequisites

- Node.js 22+
- pnpm 10.26.2+

### Installation

```bash
# Install dependencies
pnpm install

# Copy environment variables
cp .env.example .env
# Edit .env with your configuration
```

When running through root commands such as `make dev`, most frontend variables
can stay commented out because nginx and the Next.js server use the default
local Gateway wiring.

### Development

```bash
# Start development server
pnpm dev

# The app will be available at http://localhost:3000
```

### Build & Test

```bash
# Type check
pnpm typecheck

# Check formatting
pnpm format

# Apply formatting
pnpm format:write

# Lint
pnpm lint

# Run unit tests
pnpm test

# One-time setup: install Playwright Chromium browser
pnpm exec playwright install chromium

# Run E2E tests (builds and starts production server automatically)
pnpm test:e2e

# Build for production
pnpm build

# Start production server
pnpm start
```

## Site Map

```
├── /                    # Landing page
├── /workspace/chats               # Chat list
├── /workspace/chats/new           # New chat page
└── /workspace/chats/[thread_id]    # A specific chat page
```

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for full list):

```bash
# Backend API URL (optional, uses local Next.js/nginx proxy by default)
NEXT_PUBLIC_BACKEND_BASE_URL="http://localhost:8001"
# LangGraph-compatible API URL (optional, uses local Next.js/nginx proxy by default)
NEXT_PUBLIC_LANGGRAPH_BASE_URL="http://localhost:8001/api"
```

The default proxy keeps authenticated requests on the frontend origin. A
separate backend port on the same hostname also works when gateway CORS permits
the frontend origin: REST and SDK requests include session cookies and CSRF
headers. Unrelated hostnames are not supported merely by changing these URLs;
the gateway's host-only cookies and SameSite rules still apply.

## Project Structure

The workspace provides the shared chat and Agent catalog. Agent chat extensions
are selected by catalog metadata; the extension registry currently has no
domain-specific entries. Generic capability inputs and action provenance APIs
remain available for future integrations. Regular attachments, including DOCX,
XLSX, and PPTX files, continue to use the upload and artifact download flows.

```
tests/
├── e2e/                    # E2E tests (Playwright, Chromium, mocked backend)
└── unit/                   # Unit tests (mirrors src/ layout)
src/
├── app/                    # Next.js App Router pages
│   ├── api/                # API routes
│   ├── workspace/          # Main workspace pages
│   └── mock/               # Mock/demo pages
├── components/             # React components
│   ├── ui/                 # Reusable UI components
│   ├── workspace/          # Workspace-specific components
│   ├── landing/            # Landing page components
│   └── ai-elements/        # AI-related UI elements
├── core/                   # Core business logic
│   ├── api/                # API client & data fetching
│   ├── artifacts/          # Artifact management
│   ├── config/              # App configuration
│   ├── i18n/               # Internationalization
│   ├── mcp/                # MCP integration
│   ├── messages/           # Message handling
│   ├── models/             # Data models & types
│   ├── settings/           # User settings
│   ├── skills/             # Skills system
│   ├── threads/            # Thread management
│   ├── todos/              # Todo system
│   └── utils/              # Utility functions
├── hooks/                  # Custom React hooks
├── lib/                    # Shared libraries & utilities
├── server/                 # Server-side code
│   └── better-auth/        # Authentication setup and session helpers
└── styles/                 # Global styles
```

## Scripts

| Command             | Description                             |
| ------------------- | --------------------------------------- |
| `pnpm dev`          | Start development server with Turbopack |
| `pnpm dev:webpack`  | Start development server with webpack   |
| `pnpm build`        | Build for production                    |
| `pnpm start`        | Start production server                 |
| `pnpm test`         | Run unit tests with Rstest              |
| `pnpm test:e2e`     | Run E2E tests with Playwright           |
| `pnpm format`       | Check formatting with Prettier          |
| `pnpm format:write` | Apply formatting with Prettier          |
| `pnpm lint`         | Run ESLint                              |
| `pnpm lint:fix`     | Fix ESLint issues                       |
| `pnpm typecheck`    | Run TypeScript type checking            |
| `pnpm check`        | Run both lint and typecheck             |

## Development Notes

- Uses pnpm workspaces (see `packageManager` in package.json)
- Development uses Turbopack by default for fast rebuilds.
- Webpack remains available with `pnpm dev:webpack` when testing bundler-specific behavior.
- Environment validation can be skipped with `SKIP_ENV_VALIDATION=1` (useful for Docker)
- Backend API URLs are optional; nginx proxy is used by default in development

## License

MIT License. See [LICENSE](../LICENSE) for details.

# Documentation

This directory contains detailed documentation for the reusable VassilFlow agent
backend. The base ships no built-in product Agents; the capability, Action,
lifecycle, and repository extension contracts remain available.

## Quick Links

| Document                                               | Description                                                               |
| ------------------------------------------------------ | ------------------------------------------------------------------------- |
| [ARCHITECTURE.md](ARCHITECTURE.md)                     | Canonical runtime, Agent, capability, project, and extension architecture |
| [CORE_BACKEND_AUDIT.md](CORE_BACKEND_AUDIT.md)         | Evidence-based core backend architecture, LOC, and resource audit         |
| [CORE_BACKEND_REFACTOR_PLAN.md](CORE_BACKEND_REFACTOR_PLAN.md) | Staged performance, simplification, and selective Go migration plan |
| [API.md](API.md)                                       | Complete API reference                                                    |
| [AUTH_DESIGN.md](AUTH_DESIGN.md)                       | User authentication, CSRF, and per-user isolation design                  |
| [CONFIGURATION.md](CONFIGURATION.md)                   | Configuration options                                                     |
| [../../docs/PERSISTENCE.md](../../docs/PERSISTENCE.md) | Storage authority, readiness, backup, repository operations, and repair   |
| [../../docs/SETUP.md](../../docs/SETUP.md)             | Full fresh-clone setup guide                                              |
| [SETUP.md](SETUP.md)                                   | Backend-only setup notes                                                  |

## Feature Documentation

| Document                                                   | Description                                                                                           |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [STREAMING.md](STREAMING.md)                               | Token-level streaming design: Gateway vs VassilFlowClient path, `stream_mode` semantics, per-id dedup |
| [FILE_UPLOAD.md](FILE_UPLOAD.md)                           | File upload functionality                                                                             |
| [PATH_EXAMPLES.md](PATH_EXAMPLES.md)                       | Path types and usage examples                                                                         |
| [SANDBOX_MEMORY_PROFILING.md](SANDBOX_MEMORY_PROFILING.md) | Sandbox memory baseline and runtime comparison guide                                                  |
| [summarization.md](summarization.md)                       | Context summarization feature                                                                         |
| [plan_mode_usage.md](plan_mode_usage.md)                   | Plan mode with TodoList                                                                               |
| [AUTO_TITLE_GENERATION.md](AUTO_TITLE_GENERATION.md)       | Automatic title generation                                                                            |

## Development

| Document           | Description                       |
| ------------------ | --------------------------------- |
| [TODO.md](TODO.md) | Planned features and known issues |

## Getting Started

1. **New to VassilFlow?** Start with [../../docs/SETUP.md](../../docs/SETUP.md) for fresh-clone setup
2. **Configuring the system?** See [CONFIGURATION.md](CONFIGURATION.md)
3. **Understanding the architecture?** Read [ARCHITECTURE.md](ARCHITECTURE.md)
4. **Building integrations?** Check [API.md](API.md) for API reference

## Document Organization

```text
docs/
|-- README.md                  # This file
|-- ARCHITECTURE.md            # System architecture
|-- API.md                     # API reference
|-- AUTH_DESIGN.md             # User authentication and isolation design
|-- CONFIGURATION.md           # Configuration guide
|-- SETUP.md                   # Backend-only setup notes
|-- FILE_UPLOAD.md             # File upload feature
|-- PATH_EXAMPLES.md           # Path usage examples
|-- summarization.md           # Summarization feature
|-- plan_mode_usage.md         # Plan mode feature
|-- STREAMING.md               # Token-level streaming design
|-- AUTO_TITLE_GENERATION.md   # Title generation
|-- TITLE_GENERATION_IMPLEMENTATION.md  # Title implementation details
`-- TODO.md                    # Roadmap and issues
```

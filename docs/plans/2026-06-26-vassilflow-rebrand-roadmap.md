# VassilFlow Rebrand Roadmap

## Scope

This roadmap separates product identity work from runtime compatibility work. The current baseline is runnable because the DeerFlow package namespace, environment variable names, Docker service names, and persisted state paths still match the code.

The migration should therefore happen in small commits that each keep the application runnable.

## Reference Classes

- Product surface: UI copy, page metadata, repository links, OpenAPI title/description, channel bot replies, generated credential headers, export filenames.
- Public compatibility surface: HTTP headers, environment variables, config keys, Docker compose service names, CLI command names, generated runtime paths.
- Internal implementation surface: Python package names, TypeScript package names, module paths, import strings, tests that patch exact module paths.
- Historical documentation: upstream issue references, comments that describe inherited behavior, research notes, source reports.

## Phase 1 - Product Surface Identity

Change user-visible product identity to VassilFlow while preserving runtime compatibility.

Allowed:

- `DeerFlow` text in visible UI and i18n strings.
- Landing/auth/workspace branding.
- GitHub links that point users at the project repository.
- OpenAPI app title, description, and health service name.
- IM channel connection instructions and success messages.
- Local admin credential file header.
- Downloaded memory export filename prefix.

Deferred:

- `deerflow.*` Python imports and config provider paths.
- `DEER_FLOW_*` environment variables.
- `X-DeerFlow-*` internal gateway headers.
- `.deer-flow` runtime directories.
- Docker compose project/container names.
- npm/Python package names.
- Historical upstream issue links and compatibility comments.

## Phase 2 - Compatibility Aliases

Add VassilFlow aliases before renaming anything relied on by users or deployments.

- Status: backend/runtime/frontend env aliases, Docker/script env bridges, and
  precedence documentation are implemented; Docker service/container renames
  remain deferred.
- Support `VASSILFLOW_*` env vars alongside `DEER_FLOW_*`.
- Add VassilFlow-named config aliases where the old names are user-facing.
- Add tests proving old and new names resolve to the same runtime behavior.
- Document precedence rules when both old and new names are set.

## Phase 3 - Facade Modules

Add VassilFlow-owned facade modules over existing DeerFlow internals.

- Status: initial `vassilflow` Python facade package is implemented with
  boundary dataclasses/enums mirrored from
  `contracts/vassilflow_boundary_contract.json`; dynamic config class paths now
  accept `vassilflow.*` and the setup wizard/config examples prefer those names.
  Deeper internal import renames remain deferred.
- Keep existing `deerflow` imports working.
- Introduce stable VassilFlow names for session, run, trace, tool, policy, approval, memory, and completion evidence contracts.
- Add tests around `contracts/vassilflow_boundary_contract.json`.
- Keep behavior unchanged until the facade is covered.

## Phase 4 - Repository And Package Renames

Rename files, package names, Docker names, and module paths only after alias tests exist.

- Status: Docker Compose project/container/network names and sandbox container
  prefixes now default to `vassilflow-*`; scripts still clean up legacy
  `deer-flow-*` stacks and sandbox containers during the transition. Runtime
  state now defaults to `.vassilflow` for fresh workspaces while preserving
  existing `.deer-flow` directories as an automatic fallback.
- Rename one ownership boundary at a time.
- Leave deprecation shims for at least one migration window.
- Update docs and examples in the same commit as each supported alias.

## Phase 5 - Historical Docs Cleanup

Rewrite inherited README/docs after runtime aliases and facade modules are stable.

Status: README and frontend English/Chinese product docs now use VassilFlow for
standalone product references. `VassilFlowClient` and
`create_vassilflow_agent` are now the documented embedded SDK entrypoints while
legacy `deerflow.*`, `DeerFlowClient`, and `create_deerflow_agent` imports
remain supported as compatibility shims.

Historical upstream references should remain where they explain provenance, fixes, or compatibility decisions. Product docs should use VassilFlow.

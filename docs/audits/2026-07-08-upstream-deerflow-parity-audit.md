# Upstream Parity Audit - 2026-07-08

This audit tracks upstream commits in `research/superagent-harness/deer-flow`
against the current VassilFlow tree and records which changes have been ported,
which still need a VassilFlow-native port, and which do not apply.

## Legend

- `DA CO`: equivalent behavior already exists in VassilFlow.
- `CAN PORT`: upstream behavior is missing or only partially present and should be ported.
- `KHONG PHU HOP`: upstream change does not apply cleanly to the current VassilFlow product
  surface, or depends on a subsystem that VassilFlow has not adopted.

## Highest Priority Port Candidates

| Commit | Status | Decision |
| --- | --- | --- |
| `b81334cc` | DA CO | Ported as VassilFlow `ReadBeforeWriteMiddleware`, config, sandbox read helper, and tests. |
| `576577bd` | DA CO | Ported as `VASSILFLOW_CHANNEL_USER_ID` command-prefix injection plus task/subagent context propagation. |
| `4d660b20` | DA CO | Request-scoped secrets core and gateway stripping of caller-supplied internal `__*` context keys are present. |
| `84bbdf6e` | DA CO | Langfuse user metadata now resolves through runtime context via `resolve_runtime_user_id(runtime)`. |
| `e9de1874` | DA CO | Provisioner sandbox business routes are sync handlers so Kubernetes client calls run off the ASGI event loop; regression test added. |
| `f0f9dd66` | DA CO | Setup wizard now prompts custom OpenAI-compatible gateways for thinking support and writes the matching toggles without mutating provider definitions. |
| `4669d3c0` | DA CO | Cache-aware token/cost accounting, console router, pricing metadata handling, docs, and tests are ported. |
| `00161811` | DA CO | Workspace change review is ported: backend snapshot/diff recorder, run endpoint, frontend badge/panel, docs, and tests. |
| `7a985f44` | DA CO | Applicable mobile workspace, landing overflow, mobile nav, focus-ring, and trigger accessibility fixes are ported in VassilFlow terms. |
| `c22c955c` | DA CO | Feishu top-level file/image messages are batched into one inbound thread window with regression coverage. |
| `b85c672c` | DA CO | WeChat state/file filesystem IO is offloaded via `asyncio.to_thread`; blocking-IO tests added. |
| `e9161ff1` | DA CO | Discord thread-store load/persist and attachment reads are offloaded via `asyncio.to_thread`; blocking-IO tests added. |

## Detailed Commit Matrix

### Runtime, Memory, Branching, Journal

| Commit | Status | Notes |
| --- | --- | --- |
| `28f2b07b` | DA CO | Memory freshness/staleness handling has been ported. |
| `186c6ea4` | DA CO | Assistant turn branching is present in backend and frontend. |
| `26d7a597` | DA CO | Manual context compaction endpoint, runtime compactor, middleware, and tests are present. |
| `8fbcdf82` | DA CO | Journal hidden/card tool message reconciliation and `human_input_response` handling are present. |
| `442248dd` | DA CO | Durable context preservation across summarization is present. |
| `f6564402` | DA CO | Dynamic context ID swap handling is present. |
| `820560e5` | DA CO | Run event store indexes by run index. |
| `346164d7` | DA CO | Memory run store thread indexing is present. |
| `bf702803` | DA CO | Hidden human messages are filtered for memory extraction. |
| `8167275c` | DA CO | Whitespace-only facts are skipped. |
| `b990da78` | DA CO | Correction facts are injected. |
| `90fdda77` | DA CO | Journal skips hidden human messages. |
| `e5a610e8` | DA CO | Run journal ignores middleware prompt noise. |
| `4e6248f0` | DA CO | Recursion limit clamp is present. |
| `25ea6970` | CAN PORT | Goal continuations are not present. This is a product/runtime decision. |
| `e3e5c73b` | CAN PORT | Trace correlation middleware is not present as an equivalent standalone layer. |

### Tools, Skills, Sandbox

| Commit | Status | Notes |
| --- | --- | --- |
| `658c39cc` | DA CO | SkillScan-style skill discovery is present. |
| `15454b6f` | DA CO | Deferred skill discovery is present. |
| `fd41fdb0` | DA CO | Tool progress metadata exists and the read-before-write outer guard is now wired before ToolProgress/ToolErrorHandling. |
| `b81334cc` | DA CO | Dedicated read-before-write middleware is present. |
| `09988caf` | DA CO | Request-scoped secrets core is present. |
| `4d660b20` | DA CO | Internal caller metadata stripping is present. |
| `80e031dc` | DA CO | Subagent loop detection is present. |
| `857fb962` | DA CO | Sandbox setup pins `all-in-one-sandbox:1.11.0`. |
| `48477d86` | DA CO | All-in-one sandbox missing-image failure path is handled. |
| `fe825520` | DA CO | Local sandbox command timeout behavior is covered. |
| `b0ce4b51` | DA CO | Heredoc sandbox audit behavior is present. |
| `30841c3b` | DA CO | Sandbox provider singleton lifecycle lock, orphan shutdown, reset/shutdown detach semantics, and concurrency tests are present. |
| `4f192cb4` | DA CO | Sandbox artifact mounts and acquisition are user-scoped across Feishu, uploads, local sandbox, AIO provider, and provisioner paths. |
| `1f740829` | CAN PORT | Crawl4AI package is absent. Port only if this provider remains part of VassilFlow's tool strategy. |
| `a8f950fe` | CAN PORT | Browserless `web_capture` tool is absent. |
| `e5424cba` | CAN PORT | E2B sandbox provider is absent. This is a provider strategy decision. |
| `358bacad` | CAN PORT | BoxLite sandbox scaffold is absent. |
| `67c8ade3` | CAN PORT | BoxLite warm pool/shared mixin is absent. Existing AIO warm pool is separate. |

### Channels And Integrations

| Commit | Status | Notes |
| --- | --- | --- |
| `576577bd` | DA CO | `channel_user_id` reaches sandbox commands as `VASSILFLOW_CHANNEL_USER_ID` and propagates through delegated subagents. |
| `c22c955c` | DA CO | Feishu file batching is ported with parser regression tests for top-level files, rich-text files, replies, and expired batches. |
| `7ea72087` | DA CO | Feishu no-thread replies, P2P topic behavior, stream throttling, cursor indicator, and clarification snapshot handling are ported. |
| `dcb2e687` | CAN PORT | GitHub webhook channel is absent. Also carries token injection and transient error handling pieces. |
| `4fc08b4f` | CAN PORT | Scheduled tasks are absent. |
| `b85c672c` | DA CO | WeChat constructor/start/auth/state/file staging paths are now IO-safe on async paths. |
| `e9161ff1` | DA CO | Discord startup thread mapping, persistence, and file upload reads are IO-safe on async paths. |
| `7a6c4a99` | CAN PORT | Per-chat thread creation serialization should be rechecked against current channel repository behavior. |
| `69cf4f4d` | DA CO | Notification hook behavior appears present in the current channel/runtime layer. |

### Frontend And UX

| Commit | Status | Notes |
| --- | --- | --- |
| `4915b5e4` | DA CO | Regenerate support for custom agent chats is present. |
| `47b0f604` | DA CO | Human input card flow is present; sidecar-specific parts do not apply yet. |
| `c05c1899` | DA CO | Message copy/uploaded-file context cleanup is present. |
| `2ebe5cf0` | DA CO | Composer focus-ring masking utility is present. |
| `f1225944` | DA CO | Placeholder utility and tests are present. |
| `7a985f44` | DA CO | Ported VassilFlow-native landing overflow guards, mobile nav, responsive section gutters, mobile artifact drawer, stable `useIsMobile`, visible focus-ring tokens, and trigger ARIA/test hooks. Upstream scheduled-task link does not apply because that UI is absent. |
| `6a4e5a3b` | DA CO | Side conversations are ported with VassilFlow metadata, main-chat quote attachments, side chat creation/restore, hidden context prompts, primary thread-list filtering, cascade delete, mock API support, unit tests, and e2e coverage. |
| `34f87f6c` | DA CO | Side chat panel delete behavior is ported: the panel button deletes persisted side chats with confirmation, draft close discards references, local delete 404 is idempotent, and e2e coverage exercises the flow. |
| `cb83edb0` | DA CO | Side chat text-selection toolbar is ported: sidecar-surface selections hide "Ask in side chat" and attach quotes to the side chat composer. |
| `48e5856c` | KHONG PHU HOP | Localized upstream README edits do not map to the current VassilFlow docs structure. |
| `a817a0ed` | DA CO | Frontend reconnect/cancel behavior is present. |
| `8a26b5c9` | DA CO | Citation source panel behavior is present. |
| `22290c16` | DA CO | Frontend summarization preservation is present. |
| `3e2f1bbe` | DA CO | Artifact filename behavior for presented artifacts is present. |
| `7c8a17c6` | DA CO | Artifacts are preserved during streaming. |
| `b3c312b7` | DA CO | Artifact dropdown regression appears covered. |
| `14d9bb87` | DA CO | Prompt history recall is present in frontend e2e coverage. |
| `b5cac5e7` | DA CO | Artifact markdown preview now uses `rehype-slug` through a preview-only plugin config; unit and e2e anchor-scroll coverage are present. |
| `11415875` | DA CO | Recent chat rows already use a full-row link with the action separated; blank-space click e2e coverage is present. |

### API, Gateway, Config, Observability

| Commit | Status | Notes |
| --- | --- | --- |
| `a4a88fda` | DA CO | MCP session pool singleton lifecycle is present. |
| `927b833e` | DA CO | Guardrail internal owner attribution is present. |
| `8cde7f25` | DA CO | Multi-worker non-Postgres gate is present. |
| `f6a910de` | DA CO | `api_base` to `base_url` normalization is present. |
| `12eda6c7` | DA CO | SSRF URL safety guard is present for current Browserless/FastCRW surfaces. |
| `5acd0b3b` | DA CO | Upload file IO is offloaded. |
| `f0f9dd66` | DA CO | Setup wizard thinking prompt/helper and regression tests are present for the custom OpenAI-compatible provider. |
| `84bbdf6e` | DA CO | Langfuse user attribution resolves from runtime context. |
| `4669d3c0` | DA CO | Cache-aware token/cost accounting, `/api/console` stats/runs/usage endpoints, pricing metadata stripping, docs, and tests are ported. |
| `972096db` | DA CO | Console-router test compatibility is covered by the VassilFlow-native console router regression suite. |
| `6060d95e` | DA CO | DeepSeek provider, patched-provider tests, config examples, mock model endpoint, and docs now use the V4 model names. |
| `a59f9d42` | DA CO | Provisioner sandbox container port is configurable via `SANDBOX_CONTAINER_PORT`, exposed through compose/docs, and covered by manifest tests. |
| `c9a5f23e` | DA CO | MCP `tool_call_timeout` for stdio servers is ported in schema, docs/examples, wrapper runtime, warnings, and regression tests. |
| `70d53da7` | DA CO | HTTPS `csrf_token` cookies now persist for the same lifetime as `access_token`; HTTP remains session-only and tests cover both mint sites. |
| `dd05e1a7` | DA CO | Production Docker build/deploy now expands multi-value `UV_EXTRAS`, loads `.env` safely, auto-detects extras, updates docs, and has regression tests. |
| `71c5c4a0` | DA CO | Docker and local nginx configs preserve upstream `X-Forwarded-Proto` through `$forwarded_proto`; regression tests cover both files. |
| `b66e3253` | DA CO | AppConfig indexes are present. |
| `f956682f` | DA CO | SSE resume offset optimization is present. |

### Storage, Uploads, Files, Database

| Commit | Status | Notes |
| --- | --- | --- |
| `53a80d3a` | DA CO | User-scoped skill storage appears present in the current skills storage layer. |
| `76aa5991` | DA CO | Upload manifest/limit handling appears present. |
| `9d7e1313` | DA CO | Lead skill loading/read-file preservation appears present. |
| `e5d36187` | DA CO | Guardrail run-event recording is present. |
| `cd982d67` | DA CO | Windows path normalization is covered. |
| `d9305989` | DA CO | File conversion boundary handling appears present. |
| `8fa6ed2b` | DA CO | Upload rollback/staging cleanup appears present. |
| `68c968f6` | DA CO | Orphan tool message handling appears present. |
| `af0d14d2` | DA CO | Delegation ledger behavior appears present. |
| `2453718a` | DA CO | Title fallback behavior appears present. |
| `debb0fd1` | DA CO | Alembic migration structure exists. |
| `435edbd8` | DA CO | Artifact router IO offload appears present. |
| `cc1df2d0` | DA CO | `message_content_to_text` helper is present. |
| `fde6885a` | DA CO | System-message coalescing is present. |
| `cefc53c7` | DA CO | Todo positional fallback appears present. |
| `caf54938` | DA CO | Thread ID context API is present. |
| `f7f2a500` | DA CO | Path regex cache is present. |

### Web Search And External Providers

| Commit | Status | Notes |
| --- | --- | --- |
| `ddb097a7` | CAN PORT | Brave web search exists, but Brave image search is absent. VassilFlow currently uses other image search providers. |
| `37483443` | DA CO | Frontend file validation exists. |
| `46fd2813` | DA CO | Atlas-style config examples appear reflected in current config examples. |
| `0ee35ca3` | DA CO | Locale docs links appear present in the docs/frontend content. |

### Subsystems Not Adopted Or Not Yet Exposed

| Commit | Status | Notes |
| --- | --- | --- |
| `823c47bc` | DA CO | UTF-16/UTF-8-BOM workspace diff scanning fixes are ported with regression tests. |
| `38342b15` | KHONG PHU HOP | Redis stream retention recovery does not apply while Redis bridge is still not implemented. |
| `72f033fb` | KHONG PHU HOP | Same Redis stream bridge dependency. |
| `cf026464` | DA CO | VassilFlow-native support bundle is ported as `make support-bundle`, redacted zip/summary/draft generation, issue-template guidance, docs, and regression tests. |
| `ef5f54c5` | CAN PORT | TUI is absent. Port only if VassilFlow wants a CLI/TUI surface. |
| `cb3f9ac7` | KHONG PHU HOP | Docs-only TUI reference does not apply until TUI exists. |
| `ff7ecdbd` | KHONG PHU HOP | Docs-only agent guidance does not apply directly to current VassilFlow docs. |
| `ddca8641` | KHONG PHU HOP | Upstream docs cleanup is not directly portable after VassilFlow documentation rewrite. |
| `629477fd` | KHONG PHU HOP | Upstream docs cleanup is not directly portable after VassilFlow documentation rewrite. |
| `c05dd46e` | KHONG PHU HOP | Docs-only change with no current VassilFlow runtime effect. |
| `67dd75db` | KHONG PHU HOP | Dead-code cleanup does not map to an active VassilFlow feature. |

## Recommended Port Order

1. Larger product surfaces requiring an explicit VassilFlow decision: `4fc08b4f`, `dcb2e687`, `e5424cba`, `358bacad`, `67c8ade3`, `ef5f54c5`.

## Notes For The Next Fix Batch

- Do not port optional provider surfaces blindly. E2B, BoxLite, Crawl4AI, Browserless capture,
  TUI, scheduled tasks, GitHub channel, and workspace change review each expands the product
  surface and should land with VassilFlow naming, docs, config, and tests.
- Batch 1 has been ported: read-before-write guard, internal metadata stripping,
  channel user sandbox env injection, and Langfuse runtime user attribution.
- Batch 2 has been ported: provisioner K8s request threading, WeChat/Discord
  blocking-IO offload, Feishu file batching, and Feishu stream throttling/no-thread replies.
- Batch 3 has been ported: setup-wizard custom gateway thinking support,
  DeepSeek V4 naming/docs/mock parity, configurable provisioner sandbox port,
  nginx forwarded-proto preservation, and persistent HTTPS CSRF cookies.
- Batch 4 has been ported: applicable frontend polish from `7a985f44`, artifact
  markdown heading anchors from `b5cac5e7`, and recent-chat row click parity from
  `11415875`.
- Batch 5 has been ported: side conversations from `6a4e5a3b`, side chat
  toolbar ownership from `cb83edb0`, and side chat delete semantics from
  `34f87f6c`.
- Batch 6 has been reviewed/ported: sandbox provider lifecycle (`30841c3b`)
  and user-scoped sandbox artifact mounts (`4f192cb4`) were already present;
  MCP stdio `tool_call_timeout` from `c9a5f23e` is now ported.
- Batch 7 has been ported: cache-aware console/cost accounting from
  `4669d3c0` and production Docker `UV_EXTRAS` propagation from `dd05e1a7`.
- Batch 8 has started on product surfaces: support bundle generation from
  `cf026464` is ported with VassilFlow naming, `.vassilflow` paths, CLI/docs
  wiring, issue-template guidance, and redaction/thread-manifest tests.
- Batch 9 has been ported: workspace change review from `00161811` plus the
  UTF-16 workspace diff fix from `823c47bc`. VassilFlow now records run-scoped
  workspace/output changes, exposes `/workspace-changes`, renders assistant-turn
  file-change review in the workspace UI, and covers scanner/API/UI helpers with
  regression tests.
- After each port batch, run backend tests first, then targeted frontend tests if the batch
  touches UI state or streaming behavior.

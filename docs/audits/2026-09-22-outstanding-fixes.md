# Outstanding fixes — 22 September 2026

Review date: 2026-09-22.

> Historical snapshot: this report records fixes and verification against the
> working tree on this date. It is not a description or validation of the later
> `vassilflow-core` 0.1.0 release.

This round fixed confirmed issues in the working tree while preserving the
Office removal changes and earlier fixes. No commit was made, and the user's
active config and credentials were not modified. The 12 September reports
describe their respective historical states; the table below records the updated
state after this round of fixes.

## Issues addressed

| Area | Evidence and change |
| --- | --- |
| Memory queue | Safely reproduced with fake timers: 20 callbacks created an additional chain of zero-delay timers while the worker was still busy. Worker completion now schedules the next batch. The implementation preserves the debounce deadline, flush priority, owner/thread cancellation, and generation-based rejection of stale callbacks. |
| Conversation pagination | Cache rename/map operations changed the cursor from 3 to 2 when the backend included a hidden sidecar row; adding a chat to the final page also incorrectly created a new cursor. Pages now use `{ threads, nextOffset }`. All cache operations and both list interfaces preserve the backend cursor, including through TanStack structural sharing. |
| History loading | An HTTP 500 response containing `{data:[]}` was previously treated as successfully loaded empty history. HTTP status, data structure, and cursor are now checked. Loaded messages remain visible, and the main/sidecar chat shows an error and Retry history. Requests are canceled and stale results discarded when the conversation scope changes. |
| Cross-origin SDK | Actual SDK requests lacked `credentials`. Cookies are now sent by default within the configured backend origin/path. Caller-supplied credentials options and CSRF headers are preserved, and tokens are not added outside that scope. |
| Multiple Gateway workers | The guard previously permitted multiple PostgreSQL workers even though RunManager/StreamBridge remained process-local. It now accepts only 1 worker through `GATEWAY_WORKERS` and `WEB_CONCURRENCY`, validating before persistence opens. Compose passes the same worker count into the container environment so the guard can see overrides. |
| Token budget | Subagents lacked their own limit middleware; reversed hook order also caused the lead to check its budget before adding child usage. When budgeting is enabled, each child graph now has independent counters. The lead incorporates completed child usage before allowing the next tool. Budget accounting still operates when usage reporting is disabled, without adding logs/attribution. Budgeting remains disabled by default. |
| Test isolation | Running the scaffold test before the migration test left an extra `_tmp_test` table. The test model now uses separate metadata, and its engine is closed in finally. The obsolete global executor mock was removed; 7 import orders in fresh processes all used the real executor and succeeded. |
| Dialog accessibility | Associated descriptions were added at the call sites for model selection, memory fact editing, chat renaming, mobile navigation, and settings. Generated components were not modified. |

## Verification

- Backend before the fixes: **5,770 passed, 50 skipped**.
- Backend after the fixes: **5,814 passed, 50 skipped**, running all of `tests/`
  with `CI=true` and `VASSILFLOW_RUN_LIVE_TESTS=0`, except the live Docker test
  `test_sandbox_orphan_reconciliation_e2e.py`. No tests failed.
- The previously failing scaffold → migration pair passed. The related test
  group after formatting cleanup had **35 passed**.
- Frontend: **508 passed, 60 test files**; typecheck and ESLint passed.
- The frontend production build passed compilation, TypeScript checks, and
  generation of all 81 static pages. A successful build verifies packaging;
  it does not replace a real production deployment.
- Ruff passed for the Python files in this round of fixes. New/modified Python
  files were checked for formatting; unrelated preexisting formatting in the
  lead agent was retained.
- Added 3 browser specs for history errors, retry, and thread switching.
  Collection was checked; the complete Playwright suite was not run.

## Direct Chrome checks

The checks used the real frontend at `localhost:3044`, a mock API listening
only on loopback at `localhost:8049`, and isolated test data. No real model was
called in this round.

1. The API required a mock HttpOnly/SameSite=Strict cookie on SDK search
   requests. The chat list loaded across the two different ports, and the API
   recorded the cookie on the request.
2. When the messages API returned 500, the UI displayed a safe error message and
   Retry history. The current question/answer remained visible. Only one
   messages request was made during the error; there was no continuous retry
   loop.
3. After switching the fixture to 200 and clicking Retry history, older history
   appeared, the error disappeared, and current messages remained visible.
   The total messages request count was 2.
4. The model picker and chat rename dialog had accessibility descriptions.
   The console recorded no warnings or errors during the checked operations.

The tabs were closed and both test services stopped; no listeners remained on
3044/8049. Fixture code and counters were retained under
`.vassilflow/outstanding-fixes-20260922/` (Git ignored). Verification logs were
retained at `logs/outstanding-fixes-*-20260922.txt`.

## Remaining scope and limitations

- No confirmed issues remained in the list above. This does not assert that
  the entire application is free of other bugs.
- Pending memory extraction and the page's recoverable failed question remained
  in-memory state. This round did not add durability across crashes/reloads.
- Token budgets are checked after a response and require provider usage
  metadata. One response or concurrent children can exceed the remaining budget;
  this is not a reservation mechanism for a shared token pool.
- Cookies were tested across different ports on the same hostname. Unrelated
  hostnames still require proxy/auth design appropriate for host-only cookies
  and SameSite.
- Gateway still supported only one process/worker. The guard cannot detect
  every CLI invocation or replica launched by an external manager; the
  documented requirement is to keep one.
- The Codex credential loader retained its `CODEX_AUTH_PATH` or default-path
  contract. A custom `CODEX_HOME` required an explicit path, as in the earlier
  test session.
- The agent creation form returning to the naming step in development could
  not be reproduced consistently. There was insufficient evidence to fix it,
  so the flow was not changed based on speculation.
- Real Docker/PostgreSQL deployment, external channels, and every model provider
  were not tested in this round. Skips and live-test exclusions were not counted
  as passes.

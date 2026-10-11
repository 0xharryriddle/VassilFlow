# VassilFlow live usage review after Office removal

Review date: 2026-09-12.

> Historical snapshot: this report records the working tree and test environment
> on the review date. Its findings and test counts are historical evidence, not
> a description or validation of the later `vassilflow-core` 0.1.0 release.

## Review method

The review used Chrome directly with the Next.js frontend at `127.0.0.1:3044`
and the real Gateway at `127.0.0.1:8018`. Chat used the configured
`gpt-5.3-codex-spark` model, without replayed or mocked responses.

The runtime was isolated under `.vassilflow/live-smoke-20260912/`, with its own
config, SQLite database, agents, conversations, copied skills, uploads, and
outputs. The test session enabled the agent management API, used local mode
without login, and disabled channels, tracing, and background memory updates.
Existing working configuration and data were not modified.

## Flows tested

| Flow | Observed result |
| --- | --- |
| Open chat, select a model, stream a response in Vietnamese | Correct answer: `17 + 25 = 42` |
| Reload the page and continue the conversation | History remained available, and the model remembered `VASSIL-42` |
| Upload a CSV through the multipart API | HTTP 200; the upload listing contained the 35-byte file |
| Agent reads the file and creates an output | Called `read_file`, `write_file`, and `present_files`; total quantity was `12` |
| Preview and download an artifact | Markdown opened in the UI; download returned HTTP 200, with bytes matching the file on disk |
| Create an agent through conversation | Created and saved `flow-smoke-20260912` with a Vietnamese SOUL |
| Invalid or duplicate agent name | Correctly rejected, with a message in the UI |
| Catalog, search, pinning, profile, and opening chat | Worked; the new agent had available status |
| Apply a custom SOUL | Answered `[FLOW-SMOKE] 8 + 13 + 21 = 42.` |
| Branch a conversation | Created a new branch with the correct agent and history |
| Restart Gateway | Agent, conversation, upload, and artifact remained available |
| Settings: Skills/Tools | Loaded; no Office skill was present; MCP was empty as specified by the test config |
| `/workspace/office` and `/api/office/projects` | 404 |
| Old Office agent chat link | Reported that the agent was unavailable and prevented sending messages |
| Model failure before checkpoint | After the fix: preserved the question, displayed a fixed error message, and offered Restore message |
| Restore, switch model, and resend | Correct answer: `6 + 7 = 13`; the question appeared only once |
| Reasoning in Pro mode | Displayed Medium; answered `10 + 4 = 14`; the measured 2-second duration remained unchanged when the panel reopened |

The final API inventory contained **4 idle threads, 7 successful runs, and 2
known errors**. The errors were an initial failure to find credentials and a
deliberately broken model added to test recovery. No new console errors occurred
during the final two successful submissions after the fixes.

## Bugs fixed during the review

1. `RuntimeFeatures(token_budget=True)` previously created middleware with
   `enabled=False`, leaving the limit ineffective. The config was enabled when
   the flag was True, while retaining the behavior of False and explicitly
   configured middleware.
   Location: `backend/packages/harness/vassilflow/agents/factory.py`.
2. A run that failed before checkpoint caused the displayed question to
   disappear, leaving only a console error. The unsaved human message is now
   retained, the classified error is displayed using a fixed message, and the
   question can be restored to the composer for manual editing and resubmission.
   UI errors do not include tracebacks or model configuration content.
   Locations: `frontend/src/core/threads/hooks.ts`, `submission-error.ts`, and
   `frontend/src/components/workspace/chats/thread-chat-page.tsx`.
3. A nonexistent agent previously showed only a chat frame that could not send
   messages. An explanation was added after the catalog finishes loading,
   without displaying an error while loading is still in progress.
   Location: `frontend/src/components/workspace/agent-welcome.tsx`.
4. The reasoning label was empty when no custom choice had been saved. It now
   shows the same default level that the request actually uses, without changing
   how requests are sent.
   Location: `frontend/src/components/workspace/input-box.tsx`.
5. Stream completion triggered a controlled/uncontrolled warning in the
   reasoning display. An adapter now preserves the open/closed state and
   measured duration, without modifying the generated `ai-elements` component.
   Location: `frontend/src/components/workspace/messages/message-reasoning.tsx`.

These bugs were found in the shared platform; their causes should not all be
attributed to Office removal.

## Automated checks

- Backend: **5,770 passed, 50 skipped**.
  `test_sandbox_orphan_reconciliation_e2e.py` was excluded because it requires
  real Docker. The suite's live tests were disabled; the real-model runs were
  performed separately through the UI as described above.
- Frontend: **496/496 unit tests**, 58 files; typecheck and lint passed.
- A regression was added for reasoning completion. Playwright collected the
  test, but the spec was not run through an automated browser. The corresponding
  flow was exercised directly with a real model, including console checks and
  reopening the panel.
- `git diff --check`: passed.

## Remaining limitations and notes

- The existing local config had `agents_api.enabled=false`. Creating or managing
  agents through the UI requires enabling this option; it was enabled only in
  the separate test config during this review.
- The machine's Codex credentials were under `CODEX_HOME`; the loader supported
  `CODEX_AUTH_PATH` or `~/.codex/auth.json`. The test session pointed
  `CODEX_AUTH_PATH` at the existing login file. This was a configuration
  prerequisite; the provider's credential discovery mechanism was not changed.
- The attachment button opened the file chooser, but the Chrome extension
  rejected `setFiles` because file URL access had not been enabled. The complete
  UI file-selection flow was therefore not confirmed. Backend upload and use of
  the file in chat were verified.
- Recovery of a failed question remained state within the current page session.
  It was not durable across reloads if the backend had not checkpointed the
  question.
- Development warnings remained for missing accessibility descriptions in some
  dialogs. The agent creation form returned to the naming step once during the
  development session. The agent had been saved successfully, but the form reset
  could not be reproduced consistently enough to identify its cause.
- Docker/production deployment, external channels, and all other model providers
  were not tested.

## Test data and session cleanup

The two test services and test tabs were closed. The deliberately broken model
was removed from the test config/launcher. Test data was retained for reference:

- `.vassilflow/live-smoke-20260912/final-api-inventory.json`
- `.vassilflow/live-smoke-20260912/gateway.stderr.log`
- `.vassilflow/live-smoke-20260912/gateway.before-credential-override.stderr.log`
- `logs/direct-review-backend-tests.txt`
- `logs/frontend-app-review-3044-20260912.stdout.log`
- `logs/frontend-app-review-3044-20260912.stderr.log`

Runtime/config files are in Git-ignored directories. They were excluded from
commits because the test config could contain inherited credentials.

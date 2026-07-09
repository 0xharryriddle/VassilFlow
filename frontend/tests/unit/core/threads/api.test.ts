import { beforeEach, expect, test, rs } from "@rstest/core";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

beforeEach(() => {
  fetchWithAuth.mockReset();
});

test("fetchThreadTokenUsage uses shared auth fetch without JSON GET headers", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread-1",
      total_input_tokens: 3,
      total_output_tokens: 4,
      total_tokens: 7,
      total_runs: 1,
      by_model: { unknown: { tokens: 7, runs: 1 } },
      by_caller: {
        lead_agent: 0,
        subagent: 0,
        middleware: 0,
      },
    }),
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toMatchObject({
    thread_id: "thread-1",
    total_tokens: 7,
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/token-usage"),
    {
      method: "GET",
    },
  );
});

test("fetchThreadTokenUsage returns null for unavailable token usage", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 404,
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toBeNull();
});

test("compactThreadContext posts force compact request with agent name", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread 1/2",
      compacted: true,
      removed_message_count: 4,
      preserved_message_count: 2,
      summary_updated: true,
      checkpoint_id: "ckpt-new",
      total_tokens: 123,
    }),
  });
  const controller = new AbortController();
  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(
    compactThreadContext("thread 1/2", {
      signal: controller.signal,
      agentName: "research-agent",
    }),
  ).resolves.toMatchObject({
    compacted: true,
    checkpoint_id: "ckpt-new",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread%201%2F2/compact"),
    expect.objectContaining({
      method: "POST",
      signal: controller.signal,
    }),
  );
  const init = fetchWithAuth.mock.calls.at(-1)?.[1] as RequestInit;
  expect(init.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(init.body as string)).toEqual({
    force: true,
    agent_name: "research-agent",
  });
});

test("compactThreadContext surfaces backend detail on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Thread has a run in flight." }),
  });
  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(compactThreadContext("thread-1")).rejects.toThrow(
    "Thread has a run in flight.",
  );
});

test("branchThreadFromTurn posts target assistant turn", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "branch-1",
      parent_thread_id: "thread 1/2",
      parent_checkpoint_id: "ckpt-1",
      branched_from_message_id: "ai-2",
      workspace_clone_mode: "current_thread_best_effort",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread 1/2", {
      messageId: "ai-2",
      messageIds: ["ai-1", "ai-2"],
    }),
  ).resolves.toMatchObject({
    thread_id: "branch-1",
    parent_checkpoint_id: "ckpt-1",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread%201%2F2/branches"),
    expect.objectContaining({
      method: "POST",
    }),
  );
  const init = fetchWithAuth.mock.calls.at(-1)?.[1] as RequestInit;
  expect(init.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(init.body as string)).toEqual({
    message_id: "ai-2",
    message_ids: ["ai-1", "ai-2"],
  });
});

test("branchThreadFromTurn surfaces backend detail on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "This turn can no longer be branched from." }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread-1", { messageId: "ai-1" }),
  ).rejects.toThrow("This turn can no longer be branched from.");
});

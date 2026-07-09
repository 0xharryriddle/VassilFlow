import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://backend.local",
}));

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchSpy = rs.fn();

beforeEach(() => {
  fetchSpy.mockReset();
  rs.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  rs.restoreAllMocks();
});

describe("fetchWorkspaceChanges", () => {
  test("fetches workspace changes with encoded thread and run ids", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse(200, {
        available: true,
        version: 1,
        summary: {
          created: 1,
          modified: 0,
          deleted: 0,
          additions: 3,
          deletions: 0,
          truncated: false,
        },
        files: [],
        limits: {},
      }),
    );

    const { fetchWorkspaceChanges } =
      await import("@/core/workspace-changes/api");

    await expect(
      fetchWorkspaceChanges({
        threadId: "thread 1/2",
        runId: "run 1/2",
        includeFiles: false,
        includeDiff: false,
      }),
    ).resolves.toMatchObject({
      available: true,
      summary: { created: 1 },
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://backend.local/api/threads/thread%201%2F2/runs/run%201%2F2/workspace-changes?include_files=false&include_diff=false",
    );
  });

  test("surfaces backend detail when request fails", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse(500, { detail: "Workspace change store unavailable." }),
    );

    const { fetchWorkspaceChanges } =
      await import("@/core/workspace-changes/api");

    await expect(
      fetchWorkspaceChanges({
        threadId: "thread-1",
        runId: "run-1",
      }),
    ).rejects.toThrow("Workspace change store unavailable.");
  });
});

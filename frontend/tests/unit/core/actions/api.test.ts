import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "https://gateway.test",
}));

import { getAction, listActions } from "@/core/actions/api";
import { fetch as fetcher } from "@/core/api/fetcher";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("Action provenance API", () => {
  test("resolves an action and filters by resource identity", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ actions: [] }))
      .mockResolvedValueOnce(
        jsonResponse({
          schema: "vassilflow.action.v1",
          action_id: `act_${"1".repeat(32)}`,
        }),
      );

    await listActions({
      limit: 25,
      operation: "sample.edit",
      resourceKind: "sample.project",
      resourceId: "project_1",
    });
    await getAction(`act_${"1".repeat(32)}`);

    expect(mockedFetch.mock.calls[0]?.[0]).toBe(
      "https://gateway.test/api/actions?limit=25&operation=sample.edit&resource_kind=sample.project&resource_id=project_1",
    );
    expect(mockedFetch.mock.calls[1]?.[0]).toBe(
      `https://gateway.test/api/actions/act_${"1".repeat(32)}`,
    );
  });
});

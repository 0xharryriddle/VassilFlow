import { expect, rs, test } from "@rstest/core";

import { SIDECAR_METADATA_KEY } from "@/core/sidecar/thread";
import { findSidecarThreadIdsForParent } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

function makeThread(
  threadId: string,
  metadata: Record<string, unknown> = {},
): AgentThread {
  return {
    thread_id: threadId,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    metadata,
    status: "idle",
    values: { title: threadId, messages: [] },
  } as unknown as AgentThread;
}

test("finds only sidecar threads attached to the deleted parent thread", async () => {
  const search = rs.fn().mockResolvedValueOnce([
    makeThread("sidecar-1", {
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: "parent-1",
    }),
    makeThread("sidecar-other-parent", {
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: "parent-2",
    }),
    makeThread("primary-1"),
  ]);

  await expect(
    findSidecarThreadIdsForParent(
      {
        threads: {
          search,
        },
      },
      "parent-1",
    ),
  ).resolves.toEqual(["sidecar-1"]);

  expect(search).toHaveBeenCalledWith({
    metadata: {
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: "parent-1",
    },
    limit: 100,
    offset: 0,
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "metadata"],
  });
});

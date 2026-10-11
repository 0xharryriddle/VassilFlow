import { afterEach, expect, rs, test } from "@rstest/core";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://gateway.test:8001",
}));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));

import { loadArtifactContent } from "@/core/artifacts/loader";

afterEach(() => {
  rs.unstubAllGlobals();
});

test("artifact requests include credentials and preserve skill preview paths", async () => {
  const transport = rs.fn(async () => new Response("# Skill"));
  rs.stubGlobal("fetch", transport);
  const result = await loadArtifactContent({
    filepath: "/mnt/test.skill",
    threadId: "thread-a",
  });
  expect(result.content).toBe("# Skill");
  expect(transport.mock.calls[0]).toEqual([
    "http://gateway.test:8001/api/threads/thread-a/artifacts/mnt/test.skill/SKILL.md",
    expect.objectContaining({ credentials: "include" }),
  ]);
});

test.each([403, 404, 500])(
  "HTTP %s cannot become cached artifact content",
  async (status) => {
    rs.stubGlobal(
      "fetch",
      rs.fn(
        async () => new Response('{"detail":"private failure"}', { status }),
      ),
    );
    await expect(
      loadArtifactContent({ filepath: "/mnt/report.md", threadId: "thread-a" }),
    ).rejects.toThrow(`Failed to load artifact (${status})`);
  },
);

test("an expired session redirects through the shared authenticated transport", async () => {
  const location = { pathname: "/workspace/chats/thread-a", href: "" };
  rs.stubGlobal("window", { location });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => new Response("expired", { status: 401 })),
  );
  await expect(
    loadArtifactContent({ filepath: "/mnt/report.md", threadId: "thread-a" }),
  ).rejects.toThrow("Unauthorized");
  expect(location.href).toBe("/login?next=%2Fworkspace%2Fchats%2Fthread-a");
});

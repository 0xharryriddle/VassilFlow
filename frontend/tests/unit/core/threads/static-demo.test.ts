import fs from "node:fs";
import path from "node:path";

import { describe, expect, test } from "@rstest/core";

import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";

const DEMO_THREADS_DIR = path.resolve(process.cwd(), "public/demo/threads");

type DemoThread = {
  values?: {
    title?: string;
    artifacts?: string[];
    messages?: unknown[];
  };
  context?: {
    thread_id?: string;
  };
};

function readDemoThread(threadId: string): DemoThread {
  return JSON.parse(
    fs.readFileSync(
      path.join(DEMO_THREADS_DIR, threadId, "thread.json"),
      "utf8",
    ),
  ) as DemoThread;
}

function artifactPath(threadId: string, artifact: string): string {
  return path.join(
    DEMO_THREADS_DIR,
    threadId,
    artifact.replace(/^\/mnt\//, ""),
  );
}

describe("static demo threads", () => {
  test("DEMO_THREAD_IDS matches fixture directories", () => {
    const fixtureIds = fs
      .readdirSync(DEMO_THREADS_DIR, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name)
      .sort();

    expect([...DEMO_THREAD_IDS].sort()).toEqual(fixtureIds);
  });

  test("orchestrator demo is the first public fixture", () => {
    const threadId = DEMO_THREAD_IDS[0];
    const thread = readDemoThread(threadId);

    expect(threadId).toBe("vf-demo-orchestrator-run");
    expect(thread.context?.thread_id).toBe(threadId);
    expect(thread.values?.title).toBe("Superagent Orchestrator Run");
    expect(thread.values?.messages?.length).toBeGreaterThan(0);
    expect(thread.values?.artifacts).toContain(
      "/mnt/user-data/outputs/orchestrator-runbook.md",
    );
  });

  test("all declared artifacts exist on disk", () => {
    for (const threadId of DEMO_THREAD_IDS) {
      const thread = readDemoThread(threadId);

      for (const artifact of thread.values?.artifacts ?? []) {
        expect(fs.existsSync(artifactPath(threadId, artifact))).toBe(true);
      }
    }
  });
});

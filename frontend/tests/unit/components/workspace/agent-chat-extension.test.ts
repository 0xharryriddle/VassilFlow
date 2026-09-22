import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, rs, test } from "@rstest/core";

import {
  AgentChatExtension,
  isAgentChatExtensionRegistered,
} from "@/components/workspace/agents/agent-chat-extension";

const routeSource = readFileSync(
  resolve(
    process.cwd(),
    "src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx",
  ),
  "utf-8",
);
const registrySource = readFileSync(
  resolve(
    process.cwd(),
    "src/components/workspace/agents/agent-chat-extension.tsx",
  ),
  "utf-8",
);
const threadHooksSource = readFileSync(
  resolve(process.cwd(), "src/core/threads/hooks.ts"),
  "utf-8",
);
const threadTypesSource = readFileSync(
  resolve(process.cwd(), "src/core/threads/types.ts"),
  "utf-8",
);

describe("Agent chat extension boundary", () => {
  test("selects extensions through server-owned metadata on the shared route", () => {
    expect(routeSource).toContain("AgentChatExtension");
    expect(routeSource).toContain("agent?.product.chat_extension ?? null");
  });

  test("dispatches the registered extension by a server-owned key", () => {
    expect(registrySource).toContain("AGENT_CHAT_EXTENSIONS[extensionKey]");
    expect(registrySource).not.toContain("AGENT_CHAT_EXTENSIONS[agentName]");
    const manifest = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "src/components/workspace/agents/agent-chat-extensions.json",
        ),
        "utf-8",
      ),
    ) as string[];
    expect(manifest).toEqual([]);
  });

  test("the empty registry rejects unknown and prototype keys", () => {
    expect(isAgentChatExtensionRegistered("sample-selection")).toBe(false);
    expect(isAgentChatExtensionRegistered("toString")).toBe(false);
    expect(isAgentChatExtensionRegistered(null)).toBe(false);
  });

  test.each([null, "sample-selection"])(
    "renders the shared chat without an extension for %s",
    (extensionKey) => {
      const children = rs.fn(() => "shared chat");
      expect(
        AgentChatExtension({
          extensionKey,
          agentName: "sample",
          routeThreadId: "new",
          searchParams: new URLSearchParams(),
          children,
        }),
      ).toBe("shared chat");
      expect(children).toHaveBeenCalledExactlyOnceWith({});
    },
  );

  test("keeps generic capability inputs in the thread transport", () => {
    expect(threadHooksSource).toContain("capabilityInputs");
    expect(threadHooksSource).toContain("CapabilityInputEnvelope");
    expect(threadTypesSource).toContain("AgentThreadState");
  });
});

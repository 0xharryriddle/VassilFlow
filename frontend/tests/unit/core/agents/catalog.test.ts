import { describe, expect, test } from "@rstest/core";

import {
  MAX_PINNED_AGENTS,
  filterAgentCatalog,
  getPinnedAgentIdsKey,
  isSafeAgentLaunchPath,
  loadPinnedAgentIds,
  partitionPinnedAgents,
  retainAvailablePinnedAgentIds,
  savePinnedAgentIds,
  toggleAgentPin,
} from "@/core/agents/catalog";
import type { Agent, AgentCategory, AgentOrigin } from "@/core/agents/types";

function makeAgent(
  name: string,
  options: {
    origin?: AgentOrigin;
    category?: AgentCategory;
    description?: string;
    skills?: string[];
  } = {},
): Agent {
  return {
    name,
    description: options.description ?? "",
    model: null,
    tool_groups: null,
    skills: options.skills ?? null,
    soul: null,
    product: {
      id: `${options.origin ?? "personal"}:${name}`,
      display_name: name,
      origin: options.origin ?? "personal",
      category: options.category ?? "custom",
      icon: "bot",
      status: "available",
      required_tools: [],
      missing_requirements: [],
      data_access: [],
      starter_prompts: [],
      launch: {
        kind: "chat",
        path: `/workspace/agents/${name}/chats/new`,
        project_kind: null,
      },
      management: {
        can_edit: true,
        can_delete: true,
      },
    },
  };
}

function makeStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

describe("agent catalog", () => {
  test("searches across names, descriptions, and skills", () => {
    const agents = [
      makeAgent("reporter", { description: "Writes weekly updates" }),
      makeAgent("reviewer", { skills: ["security-audit"] }),
    ];

    expect(
      filterAgentCatalog(agents, {
        query: "weekly",
        origin: "all",
        category: "all",
      }).map((agent) => agent.name),
    ).toEqual(["reporter"]);
    expect(
      filterAgentCatalog(agents, {
        query: "security",
        origin: "all",
        category: "all",
      }).map((agent) => agent.name),
    ).toEqual(["reviewer"]);
  });

  test("filters by product origin", () => {
    const agents = [
      makeAgent("office", { origin: "builtin" }),
      makeAgent("proposal", { origin: "team" }),
      makeAgent("reviewer"),
    ];

    expect(
      filterAgentCatalog(agents, {
        query: "",
        origin: "team",
        category: "all",
      }).map((agent) => agent.name),
    ).toEqual(["proposal"]);
  });

  test("filters by product category", () => {
    const agents = [
      makeAgent("office", { origin: "builtin", category: "create" }),
      makeAgent("reviewer", { category: "custom" }),
    ];

    expect(
      filterAgentCatalog(agents, {
        query: "",
        origin: "all",
        category: "create",
      }).map((agent) => agent.name),
    ).toEqual(["office"]);
  });

  test("keeps pinned agents in the user's chosen order", () => {
    const agents = [makeAgent("one"), makeAgent("two"), makeAgent("three")];
    const result = partitionPinnedAgents(agents, [
      "personal:three",
      "personal:one",
    ]);

    expect(result.pinned.map((agent) => agent.name)).toEqual(["three", "one"]);
    expect(result.others.map((agent) => agent.name)).toEqual(["two"]);
  });

  test("drops stale pins before applying the pin limit", () => {
    const agents = [makeAgent("one"), makeAgent("two")];

    expect(
      retainAvailablePinnedAgentIds(
        ["personal:deleted", "personal:two", "personal:one"],
        agents,
      ),
    ).toEqual(["personal:two", "personal:one"]);
  });

  test("enforces the bounded pin list without dropping existing pins", () => {
    const existing = Array.from(
      { length: MAX_PINNED_AGENTS },
      (_, index) => `personal:agent-${index}`,
    );

    expect(toggleAgentPin(existing, "personal:extra")).toEqual({
      ids: existing,
      changed: false,
      reason: "limit",
    });
    const removedId = existing[1]!;
    expect(toggleAgentPin(existing, removedId)).toEqual({
      ids: existing.filter((id) => id !== removedId),
      changed: true,
      reason: null,
    });
  });

  test("persists only normalized VassilFlow pin IDs", () => {
    const storage = makeStorage();
    savePinnedAgentIds(
      "user/one",
      ["personal:one", "personal:one", "personal:two"],
      storage,
    );

    expect(storage.getItem(getPinnedAgentIdsKey("user/one"))).toBe(
      '["personal:one","personal:two"]',
    );
    expect(loadPinnedAgentIds("user/one", storage)).toEqual([
      "personal:one",
      "personal:two",
    ]);
  });

  test("keeps pinning usable when browser storage rejects writes", () => {
    const storage = makeStorage();
    storage.setItem = () => {
      throw new DOMException("Storage blocked", "SecurityError");
    };

    expect(() =>
      savePinnedAgentIds("user/one", ["personal:one"], storage),
    ).not.toThrow();
  });

  test("rejects unsafe launch paths", () => {
    expect(isSafeAgentLaunchPath("/workspace/agents/a/chats/new")).toBe(true);
    expect(isSafeAgentLaunchPath("https://example.com/workspace/a")).toBe(
      false,
    );
    expect(isSafeAgentLaunchPath("//example.com/workspace/a")).toBe(false);
  });
});

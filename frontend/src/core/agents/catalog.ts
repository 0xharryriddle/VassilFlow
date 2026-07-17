import type { Agent, AgentCategory, AgentOrigin } from "./types";

export const PINNED_AGENT_IDS_KEY_PREFIX = "vassilflow.agents.pinned.";
export const AGENT_PINS_CHANGED_EVENT = "vassilflow:agent-pins-changed";
export const MAX_PINNED_AGENTS = 4;

export type AgentOriginFilter = "all" | AgentOrigin;
export type AgentCategoryFilter = "all" | AgentCategory;

export interface AgentCatalogFilter {
  query: string;
  origin: AgentOriginFilter;
  category: AgentCategoryFilter;
}

export interface ToggleAgentPinResult {
  ids: string[];
  changed: boolean;
  reason: "limit" | null;
}

function normalizedQuery(query: string): string {
  return query.trim().toLocaleLowerCase();
}

function searchableAgentText(agent: Agent): string {
  return [
    agent.product.display_name,
    agent.name,
    agent.description,
    agent.model,
    agent.product.category,
    ...agent.product.required_tools,
    ...agent.product.starter_prompts,
    ...(agent.tool_groups ?? []),
    ...(agent.skills ?? []),
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLocaleLowerCase();
}

export function filterAgentCatalog(
  agents: Agent[],
  filter: AgentCatalogFilter,
): Agent[] {
  const query = normalizedQuery(filter.query);
  return agents.filter((agent) => {
    const matchesOrigin =
      filter.origin === "all" || agent.product.origin === filter.origin;
    const matchesCategory =
      filter.category === "all" || agent.product.category === filter.category;
    const matchesQuery =
      query.length === 0 || searchableAgentText(agent).includes(query);
    return matchesOrigin && matchesCategory && matchesQuery;
  });
}

export function partitionPinnedAgents(
  agents: Agent[],
  pinnedIds: string[],
): { pinned: Agent[]; others: Agent[] } {
  const pinnedOrder = new Map(
    pinnedIds.map((id, index) => [id, index] as const),
  );
  const pinned = agents
    .filter((agent) => pinnedOrder.has(agent.product.id))
    .sort(
      (left, right) =>
        pinnedOrder.get(left.product.id)! - pinnedOrder.get(right.product.id)!,
    );
  const others = agents.filter((agent) => !pinnedOrder.has(agent.product.id));
  return { pinned, others };
}

export function retainAvailablePinnedAgentIds(
  pinnedIds: string[],
  agents: Agent[],
): string[] {
  const availableIds = new Set(agents.map((agent) => agent.product.id));
  return normalizePinnedAgentIds(pinnedIds).filter((id) =>
    availableIds.has(id),
  );
}

export function normalizePinnedAgentIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return Array.from(
    new Set(value.filter((item): item is string => typeof item === "string")),
  ).slice(0, MAX_PINNED_AGENTS);
}

export function toggleAgentPin(
  pinnedIds: string[],
  agentId: string,
): ToggleAgentPinResult {
  const normalized = normalizePinnedAgentIds(pinnedIds);
  if (normalized.includes(agentId)) {
    return {
      ids: normalized.filter((id) => id !== agentId),
      changed: true,
      reason: null,
    };
  }
  if (normalized.length >= MAX_PINNED_AGENTS) {
    return { ids: normalized, changed: false, reason: "limit" };
  }
  return {
    ids: [...normalized, agentId],
    changed: true,
    reason: null,
  };
}

function browserStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getPinnedAgentIdsKey(userId: string): string {
  return `${PINNED_AGENT_IDS_KEY_PREFIX}${encodeURIComponent(userId)}`;
}

export function loadPinnedAgentIds(
  userId: string,
  storage: Storage | null = browserStorage(),
): string[] {
  if (!storage) {
    return [];
  }
  try {
    const raw = storage.getItem(getPinnedAgentIdsKey(userId));
    return raw ? normalizePinnedAgentIds(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

export function savePinnedAgentIds(
  userId: string,
  ids: string[],
  storage: Storage | null = browserStorage(),
): void {
  const normalized = normalizePinnedAgentIds(ids);
  try {
    storage?.setItem(getPinnedAgentIdsKey(userId), JSON.stringify(normalized));
  } catch {
    // Pins remain usable for the current session when storage is unavailable.
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent(AGENT_PINS_CHANGED_EVENT, {
        detail: {
          key: getPinnedAgentIdsKey(userId),
          ids: normalized,
        },
      }),
    );
  }
}

export function isSafeAgentLaunchPath(path: string): boolean {
  return path.startsWith("/workspace/") && !path.startsWith("//");
}

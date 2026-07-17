import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  Agent,
  AgentCatalog,
  AgentProductMetadata,
  CreateAgentRequest,
  UpdateAgentRequest,
} from "./types";

const BACKEND_UNAVAILABLE_STATUSES = new Set([502, 503, 504]);

export class AgentNameCheckError extends Error {
  constructor(
    message: string,
    public readonly reason: "backend_unreachable" | "request_failed",
    /**
     * Raw backend `detail` string when the failure came from a backend
     * response carrying one. `null` when no detail was provided (e.g.
     * network-layer failure, empty response body, unparseable body) — in
     * which case `message` is a generated fallback like "Failed to check
     * agent name: Bad Gateway" and the UI should prefer its own localized
     * fallback instead of surfacing the generated string.
     */
    public readonly detail: string | null = null,
  ) {
    super(message);
    this.name = "AgentNameCheckError";
  }
}

export class AgentsApiDisabledError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentsApiDisabledError";
  }
}

function isAgentsApiDisabledDetail(detail: string | undefined): boolean {
  return typeof detail === "string" && detail.includes("agents_api.enabled");
}

type AgentProductWire = Omit<
  Partial<AgentProductMetadata>,
  "launch" | "management"
> & {
  launch?: Partial<AgentProductMetadata["launch"]>;
  management?: Partial<AgentProductMetadata["management"]>;
};

type AgentWire = Omit<Agent, "product"> & {
  product?: AgentProductWire;
};

function legacyCustomAgentProduct(agent: AgentWire): AgentProductMetadata {
  return {
    id: `personal:${agent.name}`,
    display_name: agent.name,
    origin: "personal",
    category: "custom",
    icon: "bot",
    status: "available",
    required_tools: [],
    missing_requirements: [],
    data_access: [],
    starter_prompts: [],
    launch: {
      kind: "chat",
      path: `/workspace/agents/${agent.name}/chats/new`,
      project_kind: null,
    },
    management: {
      can_edit: true,
      can_delete: true,
    },
  };
}

function normalizeAgent(agent: AgentWire): Agent {
  const fallback = legacyCustomAgentProduct(agent);
  const product = agent.product;
  return {
    ...agent,
    product: product
      ? {
          ...fallback,
          ...product,
          required_tools: product.required_tools ?? [],
          missing_requirements: product.missing_requirements ?? [],
          data_access: product.data_access ?? [],
          starter_prompts: product.starter_prompts ?? [],
          launch: { ...fallback.launch, ...product.launch },
          management: { ...fallback.management, ...product.management },
        }
      : fallback,
  };
}

export async function listAgents(): Promise<Agent[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`);
  if (!res.ok) throw new Error(`Failed to load agents: ${res.statusText}`);
  const data = (await res.json()) as { agents: AgentWire[] };
  return data.agents.map(normalizeAgent);
}

export async function listAgentCatalog(): Promise<AgentCatalog> {
  const res = await fetch(`${getBackendBaseURL()}/api/agent-catalog`);
  if (!res.ok) {
    throw new Error(`Failed to load Agent catalog: ${res.statusText}`);
  }
  const data = (await res.json()) as {
    agents: AgentWire[];
    custom_agent_management_enabled?: boolean;
  };
  return {
    agents: data.agents.map(normalizeAgent),
    custom_agent_management_enabled:
      data.custom_agent_management_enabled ?? true,
  };
}

export async function getAgent(name: string): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`);
  if (!res.ok) throw new Error(`Agent '${name}' not found`);
  return normalizeAgent((await res.json()) as AgentWire);
}

export async function createAgent(request: CreateAgentRequest): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledDetail(err.detail)) {
      throw new AgentsApiDisabledError(err.detail!);
    }
    throw new Error(err.detail ?? `Failed to create agent: ${res.statusText}`);
  }
  return normalizeAgent((await res.json()) as AgentWire);
}

export async function updateAgent(
  name: string,
  request: UpdateAgentRequest,
): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to update agent: ${res.statusText}`);
  }
  return normalizeAgent((await res.json()) as AgentWire);
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${name}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete agent: ${res.statusText}`);
}

export async function checkAgentName(
  name: string,
): Promise<{ available: boolean; name: string }> {
  let res: Response;
  try {
    res = await fetch(
      `${getBackendBaseURL()}/api/agents/check?name=${encodeURIComponent(name)}`,
    );
  } catch {
    throw new AgentNameCheckError(
      "Could not reach the VassilFlow backend.",
      "backend_unreachable",
    );
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (isAgentsApiDisabledDetail(err.detail)) {
      throw new AgentsApiDisabledError(err.detail!);
    }
    if (BACKEND_UNAVAILABLE_STATUSES.has(res.status)) {
      throw new AgentNameCheckError(
        "Could not reach the VassilFlow backend.",
        "backend_unreachable",
      );
    }
    const backendDetail = typeof err.detail === "string" ? err.detail : null;
    throw new AgentNameCheckError(
      backendDetail ?? `Failed to check agent name: ${res.statusText}`,
      "request_failed",
      backendDetail,
    );
  }
  return res.json() as Promise<{ available: boolean; name: string }>;
}

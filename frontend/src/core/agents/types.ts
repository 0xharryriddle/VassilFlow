export type AgentOrigin = "builtin" | "personal" | "team";
export type AgentLaunchKind = "chat" | "project";
export type AgentAvailability = "available" | "unavailable";
export type AgentCategory =
  | "general"
  | "create"
  | "research"
  | "build"
  | "analyze"
  | "automate"
  | "custom";
export type AgentDataAccess =
  | "thread_uploads"
  | "thread_workspace"
  | "thread_outputs";

export interface AgentLaunchMetadata {
  kind: AgentLaunchKind;
  path: string;
  project_kind: string | null;
}

export interface AgentManagementMetadata {
  can_edit: boolean;
  can_delete: boolean;
}

export interface AgentProductMetadata {
  id: string;
  display_name: string;
  origin: AgentOrigin;
  category: AgentCategory;
  icon: string;
  status: AgentAvailability;
  required_tools: string[];
  missing_requirements: string[];
  data_access: AgentDataAccess[];
  starter_prompts: string[];
  launch: AgentLaunchMetadata;
  management: AgentManagementMetadata;
}

export interface Agent {
  name: string;
  description: string;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  soul?: string | null;
  product: AgentProductMetadata;
}

export interface AgentCatalog {
  agents: Agent[];
  custom_agent_management_enabled: boolean;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string;
}

export interface UpdateAgentRequest {
  description?: string | null;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  soul?: string | null;
}

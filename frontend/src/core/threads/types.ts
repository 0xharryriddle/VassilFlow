import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { CapabilityInputEnvelope } from "../capabilities";
import type { Todo } from "../todos";

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
  capability_inputs?: CapabilityInputEnvelope[];
}

export interface AgentThread extends Thread<AgentThreadState> {
  assistant_id?: string | null;
  context?: AgentThreadContext;
}

export interface RunMessage {
  run_id: string;
  seq?: number;
  content: Message;
  metadata: {
    caller: string;
    [key: string]: unknown;
  };
  created_at: string;
}

export interface ThreadTokenUsageResponse {
  thread_id: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_runs: number;
  by_model: Record<string, { tokens: number; runs: number }>;
  by_caller: {
    lead_agent: number;
    subagent: number;
    middleware: number;
  };
}

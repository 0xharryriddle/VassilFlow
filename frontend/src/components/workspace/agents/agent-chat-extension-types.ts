import type { ComponentType, ReactNode } from "react";

import type { SendMessageOptions } from "@/core/threads/hooks";

export interface AgentChatExtensionValue {
  inputContextHeader?: ReactNode;
  inputInitialValue?: string;
  submitOptions?: SendMessageOptions;
  threadPath?: (threadId: string) => string;
  onRunFinish?: () => void;
}

export interface AgentChatExtensionProps {
  extensionKey: string | null;
  agentName: string;
  routeThreadId: string;
  searchParams: Pick<URLSearchParams, "get">;
  children: (value: AgentChatExtensionValue) => ReactNode;
}

export type AgentChatExtensionComponent =
  ComponentType<AgentChatExtensionProps>;

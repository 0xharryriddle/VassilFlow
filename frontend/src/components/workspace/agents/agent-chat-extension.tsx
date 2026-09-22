"use client";

import type {
  AgentChatExtensionComponent,
  AgentChatExtensionProps,
} from "./agent-chat-extension-types";
import registeredExtensionKeys from "./agent-chat-extensions.json";

const AGENT_CHAT_EXTENSIONS: Readonly<
  Partial<Record<string, AgentChatExtensionComponent>>
> = {};

const registryKeys = Object.keys(AGENT_CHAT_EXTENSIONS).sort();
const manifestKeys = [...registeredExtensionKeys].sort();
if (
  registryKeys.length !== manifestKeys.length ||
  registryKeys.some((key, index) => key !== manifestKeys[index])
) {
  throw new Error("Agent chat extension manifest does not match the registry");
}

export function isAgentChatExtensionRegistered(
  extensionKey: string | null,
): boolean {
  return (
    extensionKey !== null && Object.hasOwn(AGENT_CHAT_EXTENSIONS, extensionKey)
  );
}

export function AgentChatExtension({
  extensionKey,
  agentName,
  routeThreadId,
  searchParams,
  children,
}: AgentChatExtensionProps) {
  const Extension = extensionKey
    ? AGENT_CHAT_EXTENSIONS[extensionKey]
    : undefined;
  if (!Extension) {
    return children({});
  }
  return (
    <Extension
      extensionKey={extensionKey}
      agentName={agentName}
      routeThreadId={routeThreadId}
      searchParams={searchParams}
    >
      {children}
    </Extension>
  );
}

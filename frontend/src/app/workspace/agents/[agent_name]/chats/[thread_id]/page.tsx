"use client";

import { PlusSquare } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { AgentChatExtension } from "@/components/workspace/agents/agent-chat-extension";
import { ThreadChatPage } from "@/components/workspace/chats/thread-chat-page";
import { Tooltip } from "@/components/workspace/tooltip";
import { iconForAgent, useAgent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

export default function AgentChatPage() {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { agent_name: agentName, thread_id: routeThreadId } = useParams<{
    agent_name: string;
    thread_id: string;
  }>();

  const { agent, isLoading: isAgentLoading } = useAgent(agentName);
  const AgentIcon = iconForAgent(agent?.product.icon ?? "bot");
  const agentDisplayName = agent?.product.display_name ?? agentName;
  const isAgentUnavailable =
    isAgentLoading || !agent || agent.product.status === "unavailable";
  const resolveAgentThreadPath = useCallback(
    (threadId: string) => `/workspace/agents/${agentName}/chats/${threadId}`,
    [agentName],
  );

  const headerIdentity = (
    <div className="flex min-w-0 shrink-0 items-center gap-1.5 rounded-md border px-2 py-1">
      <AgentIcon className="text-primary h-3.5 w-3.5" />
      <span className="hidden max-w-24 truncate text-xs font-medium sm:inline sm:max-w-none">
        {agentDisplayName}
      </span>
    </div>
  );
  const headerActions = (
    <Tooltip content={t.agents.newChat}>
      <Button
        className="px-2 sm:px-3"
        size="sm"
        variant="secondary"
        onClick={() => router.push(`/workspace/agents/${agentName}/chats/new`)}
      >
        <PlusSquare />
        <span className="hidden sm:inline">{t.agents.newChat}</span>
      </Button>
    </Tooltip>
  );
  return (
    <AgentChatExtension
      extensionKey={agent?.product.chat_extension ?? null}
      agentName={agentName}
      routeThreadId={routeThreadId}
      searchParams={searchParams}
    >
      {(extension) => (
        <ThreadChatPage
          assistantId={agentName}
          headerIdentity={headerIdentity}
          headerActions={headerActions}
          welcome={
            <AgentWelcome
              agent={agent}
              agentName={agentName}
              isLoading={isAgentLoading}
            />
          }
          inputContextHeader={extension.inputContextHeader}
          inputInitialValue={extension.inputInitialValue}
          inputDisabled={isAgentUnavailable}
          submitOptions={extension.submitOptions}
          newChatPath={`/workspace/agents/${agentName}/chats/new`}
          threadPath={extension.threadPath ?? resolveAgentThreadPath}
          onRunFinish={extension.onRunFinish}
        />
      )}
    </AgentChatExtension>
  );
}

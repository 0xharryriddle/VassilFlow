"use client";

import { PlusSquare } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { ThreadChatPage } from "@/components/workspace/chats/thread-chat-page";
import { OfficeSelectionChip } from "@/components/workspace/office/office-selection-chip";
import { Tooltip } from "@/components/workspace/tooltip";
import { iconForAgent, useAgent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import {
  officeSelectionSearchParams,
  parseOfficeSelectionSearchParams,
  resolveOfficeSelectionObject,
  useOfficePptxSelectionSurface,
  type OfficePptxObjectSelectionRequest,
} from "@/core/office";
import type { SendMessageOptions } from "@/core/threads/hooks";

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

  const [officeSelectionRequest, setOfficeSelectionRequest] =
    useState<OfficePptxObjectSelectionRequest | null>(() =>
      agentName === "office"
        ? parseOfficeSelectionSearchParams(searchParams)
        : null,
    );
  const officeSelectionQuery = useOfficePptxSelectionSurface(
    officeSelectionRequest?.project_id,
    officeSelectionRequest?.revision_id,
    officeSelectionRequest?.slide_index,
    agentName === "office" && !!officeSelectionRequest,
  );
  const officeSelectionObject = resolveOfficeSelectionObject(
    officeSelectionQuery.data,
    officeSelectionRequest,
  );
  const effectiveOfficeSelection =
    officeSelectionQuery.data?.is_current && officeSelectionObject
      ? officeSelectionRequest
      : null;

  const officeStarter =
    agentName === "office" && routeThreadId === "new"
      ? {
          presentation: t.office.presentationStarter,
          document: t.office.documentStarter,
          workbook: t.office.workbookStarter,
          "edit-selection": t.office.editSelectionStarter,
        }[searchParams.get("starter") ?? ""]
      : undefined;
  const submitOptions = useMemo<SendMessageOptions | undefined>(
    () =>
      effectiveOfficeSelection
        ? { officeSelection: effectiveOfficeSelection }
        : undefined,
    [effectiveOfficeSelection],
  );
  const resolveAgentThreadPath = useCallback(
    (threadId: string) => {
      const selectionQuery = officeSelectionRequest
        ? officeSelectionSearchParams(officeSelectionRequest).toString()
        : "";
      return `/workspace/agents/${agentName}/chats/${threadId}${selectionQuery ? `?${selectionQuery}` : ""}`;
    },
    [agentName, officeSelectionRequest],
  );
  const handleRunFinish = useCallback(() => {
    if (officeSelectionRequest) {
      void officeSelectionQuery.refetch();
    }
  }, [officeSelectionQuery, officeSelectionRequest]);
  const clearOfficeSelection = useCallback(() => {
    setOfficeSelectionRequest(null);
    history.replaceState(null, "", window.location.pathname);
  }, []);

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
  const inputContextHeader = officeSelectionRequest ? (
    <OfficeSelectionChip
      slide={officeSelectionRequest.slide_index}
      object={officeSelectionObject}
      loading={officeSelectionQuery.isLoading}
      invalid={
        officeSelectionQuery.isError ||
        (!officeSelectionQuery.isLoading &&
          (!officeSelectionObject ||
            officeSelectionQuery.data?.is_current !== true))
      }
      onClear={clearOfficeSelection}
    />
  ) : undefined;

  return (
    <ThreadChatPage
      assistantId={agentName}
      headerIdentity={headerIdentity}
      headerActions={headerActions}
      welcome={<AgentWelcome agent={agent} agentName={agentName} />}
      inputContextHeader={inputContextHeader}
      inputInitialValue={officeStarter}
      inputDisabled={isAgentUnavailable}
      submitOptions={submitOptions}
      newChatPath={`/workspace/agents/${agentName}/chats/new`}
      threadPath={resolveAgentThreadPath}
      onRunFinish={handleRunFinish}
    />
  );
}

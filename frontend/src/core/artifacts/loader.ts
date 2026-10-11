import type { BaseStream } from "@langchain/langgraph-sdk/react";

import { fetch } from "../api/fetcher";
import type { AgentThreadState } from "../threads";

import { buildWriteFileDraftContent } from "./preview";
import { urlOfArtifact } from "./utils";

export async function loadArtifactContent({
  filepath,
  threadId,
  isMock,
  signal,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  signal?: AbortSignal;
}) {
  let enhancedFilepath = filepath;
  if (filepath.endsWith(".skill")) {
    enhancedFilepath = filepath + "/SKILL.md";
  }
  const url = urlOfArtifact({ filepath: enhancedFilepath, threadId, isMock });
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to load artifact (${response.status})`);
  }
  const text = await response.text();
  return { content: text, url };
}

export function loadArtifactContentFromToolCall({
  url: urlString,
  thread,
}: {
  url: string;
  thread: BaseStream<AgentThreadState>;
}) {
  const draftContent = buildWriteFileDraftContent({
    filepath: urlString,
    messages: thread.messages,
  });
  if (draftContent !== undefined) {
    return draftContent;
  }

  const url = new URL(urlString);
  const toolCallId = url.searchParams.get("tool_call_id");
  const messageId = url.searchParams.get("message_id");
  if (messageId && toolCallId) {
    const message = thread.messages.find((message) => message.id === messageId);
    if (message?.type === "ai" && message.tool_calls) {
      const toolCall = message.tool_calls.find(
        (toolCall) => toolCall.id === toolCallId,
      );
      if (toolCall) {
        return toolCall.args.content;
      }
    }
  }
}

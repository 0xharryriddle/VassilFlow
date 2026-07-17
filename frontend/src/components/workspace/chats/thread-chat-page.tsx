"use client";

import { useParams, usePathname, useRouter } from "next/navigation";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ArtifactTrigger } from "@/components/workspace/artifacts";
import {
  ChatBox,
  useSpecificChatMode,
  useThreadChat,
} from "@/components/workspace/chats";
import { ExportTrigger } from "@/components/workspace/export-trigger";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import {
  SidecarProvider,
  SidecarTrigger,
} from "@/components/workspace/sidecar";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { Welcome } from "@/components/workspace/welcome";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildHumanInputResponseText,
  hasOpenHumanInputRequest,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings, useThreadSettings } from "@/core/settings";
import {
  useBranchThread,
  type SendMessageOptions,
  useThreadMetadata,
  useThreadStream,
  useThreadTokenUsage,
} from "@/core/threads/hooks";
import { threadTokenUsageToTokenUsage } from "@/core/threads/token-usage";
import type { AgentThread } from "@/core/threads/types";
import { pathOfThread, textOfMessage } from "@/core/threads/utils";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export type ThreadChatPageProps = {
  assistantId?: string;
  headerIdentity?: ReactNode;
  headerActions?: ReactNode;
  welcome?: ReactNode;
  inputContextHeader?: ReactNode;
  inputInitialValue?: string;
  inputDisabled?: boolean;
  submitOptions?: SendMessageOptions;
  newChatPath?: string;
  threadPath?: (threadId: string) => string;
  onRunFinish?: () => void;
};

export function ThreadChatPage({
  assistantId = "lead_agent",
  headerIdentity,
  headerActions,
  welcome,
  inputContextHeader,
  inputInitialValue,
  inputDisabled = false,
  submitOptions,
  newChatPath = "/workspace/chats/new",
  threadPath,
  onRunFinish,
}: ThreadChatPageProps = {}) {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: routeThreadId } = useParams<{ thread_id: string }>();
  const { threadId, setThreadId, isNewThread, setIsNewThread, isMock } =
    useThreadChat();
  // `isNewThread` tracks whether the backend has the thread yet — gates the
  // SDK's history fetch (see issue #2746).  `isWelcomeMode` is the visual
  // welcome layout (centered input, hero, quick actions); we flip it to false
  // the moment the user submits so the UI animates immediately, even though
  // `isNewThread` stays true until the backend actually creates the thread.
  const [isWelcomeMode, setIsWelcomeMode] = useState(isNewThread);
  const [settings, setSettings] = useThreadSettings(threadId);
  const runtimeContext = settings.context;
  const resolveThreadPath = useCallback(
    (createdThreadId: string) =>
      threadPath?.(createdThreadId) ?? `/workspace/chats/${createdThreadId}`,
    [threadPath],
  );
  const [localSettings, setLocalSettings] = useLocalSettings();
  const { tokenUsageEnabled } = useModels();
  const threadTokenUsage = useThreadTokenUsage(
    isNewThread || isMock ? undefined : threadId,
    { enabled: tokenUsageEnabled && !isMock },
  );
  const threadMetadata = useThreadMetadata(threadId, {
    enabled: !isNewThread && !isMock,
    isMock,
  });
  const branchThread = useBranchThread();
  const backendTokenUsage = threadTokenUsageToTokenUsage(threadTokenUsage.data);
  const mountedRef = useRef(false);
  const [staticDemoThread, setStaticDemoThread] = useState<AgentThread | null>(
    null,
  );
  useSpecificChatMode();

  useEffect(() => {
    mountedRef.current = true;
  }, []);

  useEffect(() => {
    if (
      assistantId !== "lead_agent" ||
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true"
    ) {
      setStaticDemoThread(null);
      return;
    }

    const pathnameThreadId = pathname.split("/").filter(Boolean).at(-1);
    const staticThreadId =
      routeThreadId && routeThreadId !== "new"
        ? routeThreadId
        : pathnameThreadId && pathnameThreadId !== "new"
          ? pathnameThreadId
          : null;
    if (!staticThreadId) {
      setStaticDemoThread(null);
      return;
    }

    let cancelled = false;
    fetch(`/demo/threads/${encodeURIComponent(staticThreadId)}/thread.json`)
      .then((response) => (response.ok ? response.json() : null))
      .then((demoThread: AgentThread | null) => {
        if (!cancelled) {
          setStaticDemoThread(
            demoThread ? { ...demoThread, thread_id: staticThreadId } : null,
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStaticDemoThread(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [assistantId, pathname, routeThreadId]);

  // Keep welcome layout in sync when navigating between threads (sidebar
  // clicks, "new chat" button).  Submitting in /chats/new flips the layout
  // via onSend below — `isNewThread` stays true until onStart, so this effect
  // is harmless during the submit transition.
  useEffect(() => {
    setIsWelcomeMode(isNewThread);
  }, [isNewThread]);

  const { showNotification } = useNotification();

  const {
    thread,
    pendingUsageMessages,
    sendMessage,
    regenerateMessage,
    isUploading,
    isHistoryLoading,
    hasMoreHistory,
    loadMoreHistory,
  } = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    displayThreadId: threadId,
    assistantId,
    context: runtimeContext,
    isMock,
    // onSend only animates the UI; do NOT flip `isNewThread` here — the
    // LangGraph SDK eagerly fetches /history the moment it receives a
    // thread id and assumes the thread exists on the backend (issue #2746).
    onSend: () => {
      setIsWelcomeMode(false);
    },
    onStart: (createdThreadId) => {
      // ! Important: Never use next.js router for navigation in this case, otherwise it will cause the thread to re-mount and lose all states. Use native history API instead.
      history.replaceState(null, "", resolveThreadPath(createdThreadId));
      setThreadId(createdThreadId);
      setIsNewThread(false);
    },
    onFinish: (state) => {
      onRunFinish?.();
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages.at(-1);
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            body =
              textContent.length > 200
                ? textContent.substring(0, 200) + "..."
                : textContent;
          }
        }
        showNotification(state.title, { body });
      }
    },
  });

  const hasThreadMessages = thread.messages.length > 0;

  useEffect(() => {
    if (isNewThread || isMock || !threadMetadata.data) {
      return;
    }

    const storedAssistantId = threadMetadata.data.assistant_id;
    const legacyAgentName = threadMetadata.data.metadata?.agent_name;
    const matchesLegacyAgentBinding =
      (storedAssistantId == null ||
        storedAssistantId === "lead_agent" ||
        storedAssistantId === "lead-agent") &&
      typeof legacyAgentName === "string" &&
      legacyAgentName === assistantId;
    if (matchesLegacyAgentBinding) {
      // A run through this route upgrades the pre-assistant_id row on the
      // server. Keep that one compatibility path reachable until migration.
      return;
    }

    const canonicalPath = pathOfThread(threadMetadata.data);
    const expectedPath =
      assistantId === "lead_agent" || assistantId === "lead-agent"
        ? `/workspace/chats/${threadId}`
        : `/workspace/agents/${encodeURIComponent(assistantId)}/chats/${threadId}`;
    if (canonicalPath !== expectedPath) {
      router.replace(canonicalPath);
    }
  }, [assistantId, isMock, isNewThread, router, threadId, threadMetadata.data]);

  useEffect(() => {
    if (
      !isNewThread &&
      !isMock &&
      threadMetadata.data === null &&
      !threadMetadata.isLoading &&
      !threadMetadata.isFetching &&
      !isHistoryLoading &&
      !hasMoreHistory &&
      !hasThreadMessages
    ) {
      router.replace(newChatPath);
    }
  }, [
    hasMoreHistory,
    hasThreadMessages,
    isHistoryLoading,
    isMock,
    isNewThread,
    newChatPath,
    router,
    threadMetadata.data,
    threadMetadata.isFetching,
    threadMetadata.isLoading,
  ]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage, options?: InputBoxSubmitOptions) => {
      const effectiveOptions = submitOptions
        ? {
            ...options,
            ...submitOptions,
            additionalKwargs: {
              ...options?.additionalKwargs,
              ...submitOptions.additionalKwargs,
            },
          }
        : options;
      const sendPromise = sendMessage(
        threadId,
        message,
        undefined,
        effectiveOptions,
      );
      if (message.files.length > 0) {
        return sendPromise;
      }
      void sendPromise;
    },
    [sendMessage, submitOptions, threadId],
  );
  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);
  const handleRegenerate = useCallback(
    (messageId: string, supersededMessageIds: string[]) =>
      regenerateMessage(threadId, messageId, supersededMessageIds),
    [regenerateMessage, threadId],
  );
  const handleBranchTurn = useCallback(
    async (messageId: string, messageIds: string[]) => {
      if (
        isNewThread ||
        isMock ||
        staticDemoThread ||
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ) {
        return;
      }

      try {
        const response = await branchThread.mutateAsync({
          threadId,
          messageId,
          messageIds,
        });
        toast.success(t.conversation.branchCreated);
        router.push(resolveThreadPath(response.thread_id));
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : t.conversation.branchFailed,
        );
      }
    },
    [
      branchThread,
      isMock,
      isNewThread,
      resolveThreadPath,
      router,
      staticDemoThread,
      t,
      threadId,
    ],
  );
  const handleSubmitHumanInput = useCallback(
    async (request: HumanInputRequest, response: HumanInputResponse) => {
      await sendMessage(
        threadId,
        {
          text: buildHumanInputResponseText(request, response),
          files: [],
        },
        undefined,
        {
          ...submitOptions,
          additionalKwargs: {
            ...submitOptions?.additionalKwargs,
            hide_from_ui: true,
            human_input_response: response,
          },
        },
      );
    },
    [sendMessage, submitOptions, threadId],
  );

  const tokenUsageInlineMode = tokenUsageEnabled
    ? localSettings.tokenUsage.inlineMode
    : "off";
  const staticDemoValues =
    staticDemoThread?.values ??
    (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ? threadMetadata.data?.values
      : undefined);
  const displayThread =
    staticDemoValues && (thread.values.messages?.length ?? 0) === 0
      ? {
          ...thread,
          values: staticDemoValues,
          messages: staticDemoValues.messages ?? [],
        }
      : thread;
  const displayThreadId = staticDemoThread?.thread_id ?? threadId;
  const hasTodos = (displayThread.values.todos?.length ?? 0) > 0;
  const hasOpenHumanInput = hasOpenHumanInputRequest(
    displayThread.messages,
    (message) => !isHiddenFromUIMessage(message),
  );
  const canSubmitHumanInput =
    !isMock &&
    !staticDemoThread &&
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";

  return (
    <ThreadContext.Provider value={{ thread: displayThread, isMock }}>
      <SidecarProvider
        parentThreadId={displayThreadId}
        context={runtimeContext}
        isMock={isMock || Boolean(staticDemoThread)}
      >
        <ChatBox threadId={displayThreadId}>
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center gap-2 px-2 sm:px-4",
                isWelcomeMode
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur",
              )}
            >
              <SidebarTrigger className="md:hidden" />
              {headerIdentity}
              <div className="flex min-w-0 flex-1 items-center text-sm font-medium">
                <ThreadTitle
                  threadId={displayThreadId}
                  thread={displayThread}
                />
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {headerActions}
                <TokenUsageIndicator
                  threadId={isNewThread ? undefined : displayThreadId}
                  backendUsage={backendTokenUsage}
                  enabled={tokenUsageEnabled}
                  messages={displayThread.messages}
                  pendingMessages={pendingUsageMessages}
                  preferences={localSettings.tokenUsage}
                  onPreferencesChange={(preferences) =>
                    setLocalSettings("tokenUsage", preferences)
                  }
                />
                <SidecarTrigger />
                <ExportTrigger threadId={displayThreadId} />
                <ArtifactTrigger />
              </div>
            </header>
            <main className="flex min-h-0 max-w-full grow flex-col">
              <div className="flex min-h-0 flex-1 justify-center">
                <MessageList
                  className={cn("size-full", !isWelcomeMode && "pt-10")}
                  threadId={displayThreadId}
                  thread={displayThread}
                  paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                  hasMoreHistory={hasMoreHistory}
                  loadMoreHistory={loadMoreHistory}
                  isHistoryLoading={isHistoryLoading}
                  tokenUsageInlineMode={tokenUsageInlineMode}
                  canRegenerate={
                    !isNewThread &&
                    !isMock &&
                    !staticDemoThread &&
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                    !isUploading &&
                    !displayThread.isLoading
                  }
                  onRegenerateMessage={handleRegenerate}
                  canBranch={
                    !isNewThread &&
                    !isMock &&
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                    !isUploading &&
                    !displayThread.isLoading &&
                    !branchThread.isPending
                  }
                  onBranchTurn={handleBranchTurn}
                  onSubmitHumanInput={
                    canSubmitHumanInput ? handleSubmitHumanInput : undefined
                  }
                />
              </div>
              <div
                className={cn(
                  "right-0 bottom-0 left-0 z-30 flex justify-center px-3 sm:px-4",
                  isWelcomeMode ? "absolute" : "relative shrink-0 pb-4",
                )}
              >
                <div
                  className={cn(
                    "relative w-full",
                    isWelcomeMode &&
                      "-translate-y-[calc(50vh-48px)] sm:-translate-y-[calc(50vh-96px)]",
                    isWelcomeMode
                      ? "max-w-(--container-width-sm)"
                      : "max-w-(--container-width-md)",
                  )}
                >
                  {hasTodos && (
                    <div
                      className={cn(
                        "right-0 left-0 z-0",
                        isWelcomeMode ? "absolute -top-4" : "relative",
                      )}
                    >
                      <div
                        className={cn(
                          "right-0 bottom-0 left-0",
                          isWelcomeMode ? "absolute" : "relative",
                        )}
                      >
                        <TodoList
                          className="bg-background/5"
                          todos={displayThread.values.todos ?? []}
                          hidden={false}
                        />
                      </div>
                    </div>
                  )}
                  {mountedRef.current ? (
                    <InputBox
                      className={cn(
                        "bg-background/5 w-full",
                        isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                      )}
                      isWelcomeMode={isWelcomeMode}
                      threadId={displayThreadId}
                      initialValue={inputInitialValue}
                      autoFocus={isWelcomeMode}
                      status={
                        thread.error
                          ? "error"
                          : displayThread.isLoading
                            ? "streaming"
                            : "ready"
                      }
                      context={settings.context}
                      contextHeader={inputContextHeader}
                      extraHeader={
                        isWelcomeMode &&
                        (welcome ?? <Welcome mode={settings.context.mode} />)
                      }
                      disabled={
                        isMock ||
                        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                        inputDisabled ||
                        isUploading ||
                        hasOpenHumanInput
                      }
                      onContextChange={(context) =>
                        setSettings("context", context)
                      }
                      onSubmit={handleSubmit}
                      onStop={handleStop}
                    />
                  ) : (
                    <div
                      aria-hidden="true"
                      className={cn(
                        "bg-background/5 h-32 w-full rounded-2xl",
                        isWelcomeMode && "-translate-y-2 sm:-translate-y-4",
                      )}
                    />
                  )}
                  {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                    <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                      {t.common.notAvailableInDemoMode}
                    </div>
                  )}
                </div>
              </div>
            </main>
          </div>
        </ChatBox>
      </SidecarProvider>
    </ThreadContext.Provider>
  );
}

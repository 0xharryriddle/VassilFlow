/**
 * Shared mock helpers for E2E tests.
 *
 * Intercepts all LangGraph / Backend API endpoints so tests can run without
 * a real backend.  Each test file imports `mockLangGraphAPI` and
 * `handleRunStream` from here.
 */

import type { Page, Route } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants — deterministic IDs used across tests
// ---------------------------------------------------------------------------

export const MOCK_THREAD_ID = "00000000-0000-0000-0000-000000000001";
export const MOCK_THREAD_ID_2 = "00000000-0000-0000-0000-000000000002";
export const MOCK_SIDECAR_THREAD_ID = "00000000-0000-0000-0000-0000000000aa";
export const MOCK_RUN_ID = "00000000-0000-0000-0000-000000000099";

const MOCK_AUTH_USER = {
  id: "default",
  email: "default@test.local",
  system_role: "admin",
  needs_setup: false,
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MockThread = {
  thread_id: string;
  title?: string;
  updated_at?: string;
  assistant_id?: string;
  /** Legacy fixture hint; converted to assistant_id on the wire. */
  agent_name?: string;
  metadata?: Record<string, unknown>;
  messages?: unknown[];
  artifacts?: string[];
};

export type MockAgent = {
  name: string;
  description?: string;
  system_prompt?: string;
  model?: string | null;
  tool_groups?: string[] | null;
  skills?: string[] | null;
  product?: Record<string, unknown>;
};

export type MockSkill = {
  id: string;
  name: string;
  description: string;
  category?: string;
  license?: string | null;
  enabled?: boolean;
};

export type MockAPIOptions = {
  threads?: MockThread[];
  agents?: MockAgent[];
  skills?: MockSkill[];
  runStreamMessages?: (route: Route, callIndex: number) => unknown[];
  customAgentManagementEnabled?: boolean;
};

const DEFAULT_SKILLS: MockSkill[] = [
  {
    id: "public:data-analysis",
    name: "data-analysis",
    description: "Analyze structured data and produce charts.",
    category: "public",
    enabled: true,
  },
  {
    id: "public:frontend-design",
    name: "frontend-design",
    description: "Create polished frontend interfaces.",
    category: "public",
    enabled: true,
  },
  {
    id: "public:disabled-skill",
    name: "disabled-skill",
    description: "Hidden from slash autocomplete.",
    category: "public",
    enabled: false,
  },
];

function isHiddenInputMessage(message: unknown) {
  if (typeof message !== "object" || message === null) {
    return false;
  }
  const additionalKwargs = Reflect.get(message, "additional_kwargs");
  return (
    typeof additionalKwargs === "object" &&
    additionalKwargs !== null &&
    Reflect.get(additionalKwargs, "hide_from_ui") === true
  );
}

function visibleInputMessages(messages: unknown[]) {
  return messages.filter((message) => !isHiddenInputMessage(message));
}

function visibleRunInputMessages(route: Route) {
  try {
    const body = route.request().postDataJSON() as {
      input?: { messages?: unknown[] };
    };
    return visibleInputMessages(body.input?.messages ?? []);
  } catch {
    return [];
  }
}

function mockStreamMessages(route?: Route, inputMessages?: unknown[]) {
  const submittedMessages = inputMessages
    ? visibleInputMessages(inputMessages)
    : route
      ? visibleRunInputMessages(route)
      : [];
  const responseMessage = {
    type: "ai",
    id: "msg-ai-1",
    content: "Hello from VassilFlow!",
  };

  if (submittedMessages.length > 0) {
    return [...submittedMessages, responseMessage];
  }

  return [
    {
      type: "human",
      id: "msg-human-1",
      content: [{ type: "text", text: "Hello" }],
    },
    responseMessage,
  ];
}

function runStreamThreadId(route: Route) {
  const pathThreadId = /\/threads\/([^/]+)\/runs\/stream/.exec(
    new URL(route.request().url()).pathname,
  )?.[1];
  if (pathThreadId) {
    return decodeURIComponent(pathThreadId);
  }

  try {
    const body = route.request().postDataJSON() as {
      thread_id?: string;
      threadId?: string;
      context?: { thread_id?: string };
      config?: { configurable?: { thread_id?: string } };
    };
    return (
      body.thread_id ??
      body.threadId ??
      body.context?.thread_id ??
      body.config?.configurable?.thread_id ??
      MOCK_THREAD_ID
    );
  } catch {
    return MOCK_THREAD_ID;
  }
}

// ---------------------------------------------------------------------------
// mockLangGraphAPI
// ---------------------------------------------------------------------------

/**
 * Mock all LangGraph API endpoints that the frontend calls on page load and
 * during message sending.  Without these mocks the pages would hang waiting
 * for a real backend.
 */
export function mockLangGraphAPI(page: Page, options?: MockAPIOptions) {
  let threads = [...(options?.threads ?? [])];
  const agents = options?.agents ?? [];
  const customAgentManagementEnabled =
    options?.customAgentManagementEnabled ?? true;
  const skills = options?.skills ?? DEFAULT_SKILLS;
  let runStreamSequence = 0;

  const upsertThread = (thread: MockThread) => {
    threads = [
      thread,
      ...threads.filter((existing) => existing.thread_id !== thread.thread_id),
    ];
  };

  const threadSearchResult = (thread: MockThread) => ({
    thread_id: thread.thread_id,
    assistant_id: thread.assistant_id ?? thread.agent_name ?? "lead_agent",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: thread.updated_at ?? "2025-01-01T00:00:00Z",
    metadata: thread.metadata ?? {},
    status: "idle",
    values: { title: thread.title ?? "Untitled" },
  });

  // Auth — keep workspace tests independent from a real gateway session.
  void page.route("**/api/v1/auth/me", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_AUTH_USER),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/v1/auth/setup-status", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ needs_setup: false }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/v1/auth/logout", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 204 });
    }
    return route.fallback();
  });

  void page.route("**/api/channels/providers", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false, providers: [] }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/channels/connections", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ connections: [] }),
      });
    }
    return route.fallback();
  });

  // Thread search — sidebar thread list & chats list page
  void page.route("**/api/langgraph/threads/search", async (route) => {
    let body = threads.map(threadSearchResult);

    let limit: number | undefined;
    let offset = 0;
    try {
      const postData = route.request().postDataJSON() as {
        limit?: number;
        offset?: number;
        metadata?: Record<string, unknown>;
      } | null;
      if (postData) {
        if (typeof postData.limit === "number") {
          limit = postData.limit;
        }
        if (typeof postData.offset === "number") {
          offset = postData.offset;
        }
        if (postData.metadata && typeof postData.metadata === "object") {
          body = body.filter((thread) =>
            Object.entries(postData.metadata ?? {}).every(
              ([key, value]) => thread.metadata?.[key] === value,
            ),
          );
        }
      }
    } catch {
      // No / invalid JSON body — fall back to returning the full list.
    }

    const sliced =
      typeof limit === "number" ? body.slice(offset, offset + limit) : body;

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(sliced),
    });
  });

  // Thread create — called when user sends first message in a new chat
  void page.route("**/api/langgraph/threads", (route) => {
    if (route.request().method() === "POST") {
      const request = route.request().postDataJSON() as {
        assistant_id?: string;
      };
      upsertThread({
        thread_id: MOCK_THREAD_ID,
        assistant_id: request.assistant_id ?? "lead_agent",
        title: "New Chat",
        updated_at: new Date().toISOString(),
        messages: mockStreamMessages(),
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: MOCK_THREAD_ID,
          assistant_id: request.assistant_id ?? "lead_agent",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          metadata: {},
          status: "idle",
          values: {},
        }),
      });
    }
    return route.fallback();
  });

  // Thread update (PATCH) — metadata update after creation
  void page.route("**/api/langgraph/threads/*", (route) => {
    const threadId = decodeURIComponent(
      new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
    );
    const matchingThread = threads.find(
      (thread) => thread.thread_id === threadId,
    );
    if (route.request().method() === "GET") {
      if (!matchingThread) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(threadSearchResult(matchingThread)),
      });
    }
    if (route.request().method() === "PATCH") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ thread_id: MOCK_THREAD_ID }),
      });
    }
    if (route.request().method() === "DELETE") {
      threads = threads.filter((thread) => thread.thread_id !== threadId);
      return route.fulfill({
        status: 204,
      });
    }
    return route.fallback();
  });

  void page.route("**/api/threads", (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as {
        thread_id?: string;
        metadata?: Record<string, unknown>;
      };
      const threadId = body.thread_id ?? MOCK_SIDECAR_THREAD_ID;
      upsertThread({
        thread_id: threadId,
        title: "Side chat",
        updated_at: new Date().toISOString(),
        metadata: body.metadata ?? {},
        messages: [],
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          thread_id: threadId,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          metadata: body.metadata ?? {},
          status: "idle",
          values: {},
        }),
      });
    }
    return route.fallback();
  });

  void page.route(/\/api\/threads\/[^/]+$/, (route) => {
    if (route.request().method() === "DELETE") {
      const threadId = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
      );
      const existed = threads.some((thread) => thread.thread_id === threadId);
      if (!existed) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Thread not found" }),
        });
      }
      threads = threads.filter((thread) => thread.thread_id !== threadId);
      return route.fulfill({
        status: 204,
      });
    }
    return route.fallback();
  });

  // Thread history — useStream fetches state history on mount
  void page.route("**/api/langgraph/threads/*/history", (route) => {
    const url = route.request().url();

    // For threads that exist in our mock data, return history with messages
    const matchingThread = threads.find((t) => url.includes(t.thread_id));
    if (matchingThread) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            values: {
              title: matchingThread.title ?? "Untitled",
              messages: matchingThread.messages ?? [
                {
                  type: "human",
                  id: `msg-human-${matchingThread.thread_id}`,
                  content: [{ type: "text", text: "Previous question" }],
                },
                {
                  type: "ai",
                  id: `msg-ai-${matchingThread.thread_id}`,
                  content: `Response in thread ${matchingThread.title ?? matchingThread.thread_id}`,
                },
              ],
              artifacts: matchingThread.artifacts ?? [],
            },
            next: [],
            metadata: {},
            created_at: "2025-01-01T00:00:00Z",
            parent_config: null,
          },
        ]),
      });
    }

    // New threads — empty history
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });

  // Thread state — getState for individual thread
  void page.route("**/api/langgraph/threads/*/state", (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const matchingThread = threads.find((t) => url.includes(t.thread_id));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          values: {
            title: matchingThread?.title ?? "Untitled",
            messages: matchingThread
              ? (matchingThread.messages ?? [
                  {
                    type: "human",
                    id: `msg-human-${matchingThread.thread_id}`,
                    content: [{ type: "text", text: "Previous question" }],
                  },
                  {
                    type: "ai",
                    id: `msg-ai-${matchingThread.thread_id}`,
                    content: `Response in thread ${matchingThread.title ?? matchingThread.thread_id}`,
                  },
                ])
              : [],
            artifacts: matchingThread?.artifacts ?? [],
          },
          next: [],
          metadata: {},
          created_at: "2025-01-01T00:00:00Z",
        }),
      });
    }
    return route.fallback();
  });

  // The URL carries a query string (e.g. `?limit=10&offset=0`), which Playwright
  // glob `*` does NOT cross, so we match with a regex anchored to `/runs`
  // followed by `?` or end-of-string.  This must NOT match `/runs/stream`.
  void page.route(/\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/, (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const matchingThread = threads.find((t) => url.includes(t.thread_id));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          matchingThread
            ? [
                {
                  run_id: `run-${matchingThread.thread_id}`,
                  thread_id: matchingThread.thread_id,
                  assistant_id:
                    matchingThread.assistant_id ??
                    matchingThread.agent_name ??
                    "lead_agent",
                  status: "success",
                  metadata: {},
                  kwargs: {},
                  created_at: "2025-01-01T00:00:00Z",
                  updated_at:
                    matchingThread.updated_at ?? "2025-01-01T00:00:00Z",
                },
              ]
            : [],
        ),
      });
    }
    return route.fallback();
  });

  void page.route(
    /\/api\/threads\/([^/]+)\/runs\/([^/]+)\/messages/,
    (route) => {
      if (route.request().method() === "GET") {
        const url = route.request().url();
        const matchingThread = threads.find((t) =>
          url.includes(`/api/threads/${t.thread_id}/runs/`),
        );
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            data: (matchingThread?.messages ?? []).map((message, index) => ({
              run_id: `run-${matchingThread?.thread_id ?? "unknown"}`,
              content: message,
              metadata: { caller: "lead_agent" },
              created_at: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
            })),
            hasMore: false,
          }),
        });
      }
      return route.fallback();
    },
  );

  // Artifact fetches from rendered historical Markdown should stay inside the
  // mocked backend during E2E runs instead of falling through to gateway rewrites.
  void page.route(/\/api\/threads\/[^/]+\/artifacts\/.+/, (route) => {
    if (route.request().method() !== "GET") {
      return route.fallback();
    }
    const pathname = new URL(route.request().url()).pathname;
    const contentType = pathname.endsWith(".svg")
      ? "image/svg+xml"
      : pathname.endsWith(".html")
        ? "text/html"
        : pathname.endsWith(".md")
          ? "text/markdown"
          : "application/octet-stream";

    return route.fulfill({
      status: 200,
      contentType,
      body: pathname.endsWith(".svg")
        ? '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#2563eb"/></svg>'
        : "",
    });
  });

  // Run stream — returns a minimal SSE response with an AI message
  const handleMockRunStream = (route: Route) => {
    runStreamSequence += 1;
    const threadId = runStreamThreadId(route);
    const existingThread = threads.find(
      (thread) => thread.thread_id === threadId,
    );
    const messages =
      options?.runStreamMessages?.(route, runStreamSequence) ??
      mockStreamMessages(route);
    upsertThread({
      thread_id: threadId,
      title: threadId === MOCK_SIDECAR_THREAD_ID ? "Side chat" : "New Chat",
      updated_at: new Date().toISOString(),
      metadata: existingThread?.metadata,
      messages,
    });
    return handleRunStreamValues(route, messages);
  };

  void page.route("**/api/langgraph/runs/stream", handleMockRunStream);
  void page.route(
    "**/api/langgraph/threads/*/runs/stream",
    handleMockRunStream,
  );

  // Models list — model picker dropdown
  void page.route("**/api/models", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          models: [],
          token_usage: { enabled: false },
        }),
      });
    }
    return route.fallback();
  });

  // Skills list — settings page and slash autocomplete
  void page.route("**/api/skills", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ skills }),
      });
    }
    return route.fallback();
  });

  // Follow-up suggestions — input box auto-suggest after AI response
  void page.route("**/api/suggestions/config", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/threads/*/suggestions", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ suggestions: [] }),
      });
    }
    return route.fallback();
  });

  // Agents list — sidebar & gallery page
  void page.route("**/api/agent-catalog", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          agents,
          custom_agent_management_enabled: customAgentManagementEnabled,
        }),
      });
    }
    return route.fallback();
  });

  void page.route("**/api/agents", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents }),
      });
    }
    return route.fallback();
  });

  // Individual agent — agent chat page
  void page.route("**/api/agents/*", (route) => {
    if (route.request().method() === "GET") {
      const url = route.request().url();
      const agent = agents.find((a) => url.endsWith(`/api/agents/${a.name}`));
      if (agent) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(agent),
        });
      }
    }
    return route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Agent not found" }),
    });
  });
}

// ---------------------------------------------------------------------------
// handleRunStream
// ---------------------------------------------------------------------------

/**
 * Build a minimal SSE stream that the LangGraph SDK can parse.
 * The stream returns a single AI message: "Hello from VassilFlow!".
 */
export function handleRunStream(route: Route, inputMessages?: unknown[]) {
  return handleRunStreamValues(route, mockStreamMessages(route, inputMessages));
}

export function handleRunStreamValues(route: Route, messages: unknown[]) {
  const threadId = runStreamThreadId(route);
  const events = [
    {
      event: "metadata",
      data: { run_id: MOCK_RUN_ID, thread_id: threadId },
    },
    {
      event: "values",
      data: {
        messages,
      },
    },
    { event: "end", data: {} },
  ];

  const body = events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join("");

  return route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body,
  });
}

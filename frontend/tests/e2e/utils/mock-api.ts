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

export type MockOfficeRenderEvidence = Record<string, unknown> & {
  evidence_id: string;
  revision_id: string;
  source_sha256: string;
};

export type MockOfficeRenderSet = {
  complete: boolean;
  page_count: number;
  rendered_page_count: number;
  evidence_ids: string[];
  evidence: MockOfficeRenderEvidence[];
};

export type MockOfficeReview = {
  review_id: string;
  revision_id: string;
  created_at: string;
  status: "approved" | "changes_requested";
  note: string | null;
  evidence_ids: string[];
  page_count: number;
  render_set_sha256: string;
};

export type MockOfficeRevision = Record<string, unknown> & {
  revision_id: string;
  parent_revision_id?: string | null;
  sequence?: number;
  kind?: string;
  artifact?: { sha256: string; size_bytes: number };
  quality?: Record<string, unknown>;
  latest_render?: MockOfficeRenderEvidence | null;
  render_set?: MockOfficeRenderSet;
  operation_receipt?: Record<string, unknown> | null;
  generation_receipt?: Record<string, unknown> | null;
  generation_preflight?: Record<string, unknown> | null;
  restored_from_revision_id?: string | null;
  latest_review?: MockOfficeReview | null;
  is_final?: boolean;
};

export type MockOfficeProject = Record<string, unknown> & {
  project_id: string;
  current_revision?: MockOfficeRevision;
  render_evidence?: MockOfficeRenderEvidence[];
  render_set?: MockOfficeRenderSet;
  final_selection?: Record<string, unknown> | null;
  generation_receipt?: Record<string, unknown> | null;
  generation_preflight?: Record<string, unknown> | null;
  revisions?: MockOfficeRevision[];
};

export type MockOfficeSelectionSurface = Record<string, unknown> & {
  project_id: string;
  revision_id: string;
  source_sha256: string;
  slide: { index: number } & Record<string, unknown>;
};

export type MockOfficeTemplateVersion = Record<string, unknown> & {
  version: number;
  status: "draft" | "published";
  slots?: Record<string, unknown>[];
  slot_candidates?: Record<string, unknown>[];
  render?: Record<string, unknown>;
};

export type MockOfficeTemplate = Record<string, unknown> & {
  template_id: string;
  title: string;
  draft_version: number | null;
  published_versions: number[];
  status: "draft" | "published";
  active_version: MockOfficeTemplateVersion;
  versions: MockOfficeTemplateVersion[];
  version_details?: MockOfficeTemplateVersion[];
};

export type MockAPIOptions = {
  threads?: MockThread[];
  agents?: MockAgent[];
  skills?: MockSkill[];
  officeProjects?: MockOfficeProject[];
  officeSelectionSurfaces?: MockOfficeSelectionSurface[];
  officeTemplates?: MockOfficeTemplate[];
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
  const officeProjects = structuredClone(options?.officeProjects ?? []);
  const officeSelectionSurfaces = structuredClone(
    options?.officeSelectionSurfaces ?? [],
  );
  const officeTemplates = options?.officeTemplates ?? [];
  let officeWorkflowSequence = 0;
  let runStreamSequence = 0;

  const publicTemplate = (template: MockOfficeTemplate) => {
    const payload = { ...template };
    delete payload.version_details;
    return payload;
  };

  const findTemplateVersion = (template: MockOfficeTemplate, version: number) =>
    template.version_details?.find((item) => item.version === version) ??
    template.versions.find((item) => item.version === version);

  const updateTemplateVersion = (
    template: MockOfficeTemplate,
    version: number,
    patch: Record<string, unknown>,
  ) => {
    const targets = [
      ...(template.version_details ?? []),
      ...template.versions,
      template.active_version,
    ];
    for (const target of targets) {
      if (target.version === version) Object.assign(target, patch);
    }
    return findTemplateVersion(template, version);
  };

  const nextOfficeId = (prefix: "ofe" | "ofr" | "ofv" | "ofs") => {
    officeWorkflowSequence += 1;
    return `${prefix}_${officeWorkflowSequence.toString(16).padStart(32, "0")}`;
  };

  const findOfficeRevision = (project: MockOfficeProject, revisionId: string) =>
    project.revisions?.find((revision) => revision.revision_id === revisionId);

  const emptyOfficeRenderSet = (): MockOfficeRenderSet => ({
    complete: false,
    page_count: 0,
    rendered_page_count: 0,
    evidence_ids: [],
    evidence: [],
  });

  const officeRenderSet = (
    project: MockOfficeProject,
    revision: MockOfficeRevision,
  ): MockOfficeRenderSet => {
    if (
      project.current_revision?.revision_id === revision.revision_id &&
      project.render_set
    ) {
      return project.render_set;
    }
    if (revision.render_set) return revision.render_set;
    const evidence = revision.latest_render ? [revision.latest_render] : [];
    if (evidence.length === 0) return emptyOfficeRenderSet();
    const pageCount = Number(evidence[0]?.page_count ?? 0);
    const renderedPageCount = Number(evidence[0]?.rendered_page_count ?? 0);
    return {
      complete: pageCount > 0 && renderedPageCount === pageCount,
      page_count: pageCount,
      rendered_page_count: renderedPageCount,
      evidence_ids: evidence.map((item) => item.evidence_id),
      evidence,
    };
  };

  const updateOfficeRevision = (
    project: MockOfficeProject,
    revision: MockOfficeRevision,
  ) => {
    const index = project.revisions?.findIndex(
      (item) => item.revision_id === revision.revision_id,
    );
    if (index !== undefined && index >= 0 && project.revisions) {
      project.revisions[index] = revision;
    }
    if (project.current_revision?.revision_id === revision.revision_id) {
      project.current_revision = revision;
    }
  };

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

  // Office Project API — Recent, project preview, revision history, and PNGs.
  void page.route("**/api/office/**", (route) => {
    const method = route.request().method();
    const pathname = new URL(route.request().url()).pathname;

    if (pathname === "/api/office/templates") {
      if (method === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            templates: officeTemplates.map(publicTemplate),
          }),
        });
      }
      if (method === "POST") {
        const template = officeTemplates[0];
        return route.fulfill({
          status: template ? 201 : 422,
          contentType: "application/json",
          body: JSON.stringify(
            template ?? { detail: "No mock Office template configured." },
          ),
        });
      }
      return route.fallback();
    }

    const templatePreviewMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/renders\/([^/]+)\/pages\/(\d+)$/.exec(
        pathname,
      );
    if (templatePreviewMatch && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAYAAAA7KqwyAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAzSURBVChTY5D3q/xPCWYAEa8//SAKg9Q+ztaBY+oZQArGagC6Tcg2omOsBpCCh4EB6BgABGBPSggMnrAAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    }

    const templateSourceMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/source$/.exec(
        pathname,
      );
    if (templateSourceMatch && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType:
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers: {
          "Content-Disposition": "attachment; filename=template.pptx",
        },
        body: Buffer.from("mock-pptx"),
      });
    }

    const templateSlotsMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/slots$/.exec(
        pathname,
      );
    if (templateSlotsMatch && method === "PUT") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateSlotsMatch[1],
      );
      const versionNumber = Number(templateSlotsMatch[2]);
      const version = template
        ? findTemplateVersion(template, versionNumber)
        : undefined;
      if (!template || !version) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Office template was not found." }),
        });
      }
      const body = route.request().postDataJSON() as {
        slots: Array<{
          key: string;
          label: string;
          type: "text" | "picture";
          candidate_id: string;
          required: boolean;
          max_length?: number;
        }>;
      };
      const candidates = version.slot_candidates ?? [];
      const slots = body.slots.map((slot) => {
        const candidate = candidates.find(
          (item) => item.candidate_id === slot.candidate_id,
        );
        return {
          key: slot.key,
          label: slot.label,
          type: slot.type,
          required: slot.required,
          candidate_id: slot.candidate_id,
          source_fingerprint: candidate?.source_fingerprint ?? "f".repeat(64),
          selector: candidate?.selector ?? {},
          constraints:
            slot.type === "text"
              ? { max_length: slot.max_length ?? 4000 }
              : {
                  accepted_media_types: ["image/png", "image/jpeg"],
                  preserve_geometry: true,
                },
          allowed_operations: [
            slot.type === "text"
              ? "replace_pptx_text"
              : "replace_pptx_picture_sources",
          ],
        };
      });
      const updated = updateTemplateVersion(template, versionNumber, {
        slots,
        slot_count: slots.length,
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updated),
      });
    }

    const templateRenderMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/render$/.exec(
        pathname,
      );
    if (templateRenderMatch && method === "POST") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateRenderMatch[1],
      );
      const versionNumber = Number(templateRenderMatch[2]);
      const version = template
        ? findTemplateVersion(template, versionNumber)
        : undefined;
      if (!template || !version) {
        return route.fulfill({ status: 404 });
      }
      const pageCount = Number(version.slide_count ?? 1);
      const evidenceId = `otr_${"9".repeat(32)}`;
      const source = version.source as { sha256?: string } | undefined;
      const render = {
        status: "available",
        evidence_id: evidenceId,
        created_at: "2026-07-17T10:10:00Z",
        source_sha256: source?.sha256 ?? "a".repeat(64),
        page_count: pageCount,
        rendered_page_count: pageCount,
        pipeline_fingerprint: "b".repeat(64),
        renderer: "VassilFlow Office Renderer",
        renderer_version: "1.0",
        visual_review_status: "not_performed",
        reviewed_at: null,
        reviewed_by: null,
        review_note: null,
        preview_pages: Array.from({ length: pageCount }, (_, index) => ({
          page: index + 1,
          source_slide: index + 1,
          width: 1600,
          height: 900,
          sha256: String(index + 1).repeat(64),
          url: `/api/office/templates/${template.template_id}/versions/${versionNumber}/renders/${evidenceId}/pages/${index + 1}`,
        })),
      };
      const updated = updateTemplateVersion(template, versionNumber, {
        render,
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updated),
      });
    }

    const templateReviewMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/renders\/([^/]+)\/review$/.exec(
        pathname,
      );
    if (templateReviewMatch && method === "POST") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateReviewMatch[1],
      );
      const versionNumber = Number(templateReviewMatch[2]);
      const version = template
        ? findTemplateVersion(template, versionNumber)
        : undefined;
      if (!template || !version || !version.render) {
        return route.fulfill({ status: 404 });
      }
      const body = route.request().postDataJSON() as {
        status: "reviewed" | "external_review_required";
      };
      const render = {
        ...version.render,
        visual_review_status: body.status,
        reviewed_at: "2026-07-17T10:12:00Z",
        reviewed_by: "default",
      };
      const updated = updateTemplateVersion(template, versionNumber, {
        render,
      });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updated),
      });
    }

    const templatePublishMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/publish$/.exec(
        pathname,
      );
    if (templatePublishMatch && method === "POST") {
      const template = officeTemplates.find(
        (item) => item.template_id === templatePublishMatch[1],
      );
      const versionNumber = Number(templatePublishMatch[2]);
      const version = template
        ? findTemplateVersion(template, versionNumber)
        : undefined;
      if (!template || !version) {
        return route.fulfill({ status: 404 });
      }
      updateTemplateVersion(template, versionNumber, {
        status: "published",
        published_at: "2026-07-17T10:15:00Z",
      });
      template.draft_version = null;
      template.published_versions = [
        ...new Set([...template.published_versions, versionNumber]),
      ];
      template.status = "published";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(findTemplateVersion(template, versionNumber)),
      });
    }

    const templateInstantiateMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)\/instantiate$/.exec(
        pathname,
      );
    if (templateInstantiateMatch && method === "POST") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateInstantiateMatch[1],
      );
      const versionNumber = Number(templateInstantiateMatch[2]);
      const version = template
        ? findTemplateVersion(template, versionNumber)
        : undefined;
      if (!template || !version || version.status !== "published") {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Published template required." }),
        });
      }
      const projectId = `ofp_${"7".repeat(32)}`;
      const revisionId = `ofr_${"8".repeat(32)}`;
      const baselineRevisionId = `ofr_${"6".repeat(32)}`;
      const evidenceId = `ofe_${"5".repeat(32)}`;
      const sourceSha = "4".repeat(64);
      const renderEvidence = {
        evidence_id: evidenceId,
        revision_id: revisionId,
        created_at: "2026-07-17T10:20:00Z",
        source_sha256: sourceSha,
        page_count: 2,
        rendered_page_count: 2,
        start_page: 1,
        end_page: 2,
        has_more: false,
        visual_review_status: "pending",
        renderer: "VassilFlow Office Renderer",
        renderer_version: "1.0",
        pipeline_fingerprint: "3".repeat(64),
        preview_pages: Array.from({ length: 2 }, (_, index) => ({
          page: index + 1,
          source_slide: index + 1,
          width: 1600,
          height: 900,
          sha256: String(index + 5).repeat(64),
          url: `/api/office/projects/${projectId}/renders/${evidenceId}/pages/${index + 1}`,
        })),
      };
      const currentRevision = {
        revision_id: revisionId,
        parent_revision_id: baselineRevisionId,
        sequence: 2,
        kind: "edit",
        created_at: "2026-07-17T10:20:00Z",
        artifact: { sha256: sourceSha, size_bytes: 132_000 },
        operation_count: 1,
        changed_target_count: 1,
        part_change_count: 1,
        relationship_change_count: 0,
        quality: {
          package_validation_status: "valid",
          preflight_status: "not_recorded",
          render_evidence_status: "available",
          visual_review_status: "pending",
        },
        latest_render: renderEvidence,
        render_set: {
          complete: true,
          page_count: 2,
          rendered_page_count: 2,
          evidence_ids: [evidenceId],
          evidence: [renderEvidence],
        },
        operation_receipt: null,
        restored_from_revision_id: null,
        latest_review: null,
        is_final: false,
      };
      officeProjects.push({
        project_id: projectId,
        title: "Quarterly company deck.pptx",
        format: "pptx",
        created_at: "2026-07-17T10:20:00Z",
        updated_at: "2026-07-17T10:20:00Z",
        primary_thread_id: null,
        revision_count: 2,
        template: {
          template_id: template.template_id,
          version: versionNumber,
          source_sha256: "a".repeat(64),
        },
        final_selection: null,
        current_revision: currentRevision,
        render_evidence: [renderEvidence],
        render_set: currentRevision.render_set,
        revisions: [currentRevision],
      });
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          template_id: template.template_id,
          template_version: versionNumber,
          project_id: projectId,
          revision_id: revisionId,
          baseline_revision_id: baselineRevisionId,
          project_title: "Quarterly company deck",
          artifact: { sha256: sourceSha, size_bytes: 132_000 },
          bound_slot_keys: ["headline"],
          omitted_optional_slot_keys: [],
          operation_count: 1,
          changed_target_count: 1,
          preflight_finding_count: 0,
          render_evidence_status: "available",
          render_evidence_ids: [evidenceId],
          project_url: `/workspace/office/projects/${projectId}`,
        }),
      });
    }

    const templateVersionMatch =
      /^\/api\/office\/templates\/([^/]+)\/versions\/(\d+)$/.exec(pathname);
    if (templateVersionMatch && method === "GET") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateVersionMatch[1],
      );
      const version = template
        ? findTemplateVersion(template, Number(templateVersionMatch[2]))
        : undefined;
      return route.fulfill({
        status: version ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          version ?? { detail: "Office template version was not found." },
        ),
      });
    }

    const templateMatch = /^\/api\/office\/templates\/([^/]+)$/.exec(pathname);
    if (templateMatch && method === "GET") {
      const template = officeTemplates.find(
        (item) => item.template_id === templateMatch[1],
      );
      return route.fulfill({
        status: template ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          template
            ? publicTemplate(template)
            : { detail: "Office template was not found." },
        ),
      });
    }

    const projectRenderMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/render$/.exec(
        pathname,
      );
    if (projectRenderMatch && method === "POST") {
      const projectId = decodeURIComponent(projectRenderMatch[1] ?? "");
      const revisionId = decodeURIComponent(projectRenderMatch[2] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const revision = project
        ? findOfficeRevision(project, revisionId)
        : undefined;
      if (!project || !revision) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Office project resource was not found.",
          }),
        });
      }

      const evidenceId = nextOfficeId("ofe");
      const sourceSha = revision.artifact?.sha256 ?? "0".repeat(64);
      const pageCount = Math.max(
        1,
        Number(revision.latest_render?.page_count ?? 2),
      );
      const evidence: MockOfficeRenderEvidence = {
        evidence_id: evidenceId,
        revision_id: revisionId,
        created_at: "2026-07-17T11:00:00Z",
        source_sha256: sourceSha,
        page_count: pageCount,
        rendered_page_count: pageCount,
        start_page: 1,
        end_page: pageCount,
        has_more: false,
        visual_review_status: "pending",
        renderer: "VassilFlow Office Renderer",
        renderer_version: "1.0",
        pipeline_fingerprint: "7".repeat(64),
        preview_pages: Array.from({ length: pageCount }, (_, index) => ({
          page: index + 1,
          source_slide: index + 1,
          width: 1600,
          height: 900,
          sha256: String((index + 7) % 10).repeat(64),
          url: `/api/office/projects/${projectId}/renders/${evidenceId}/pages/${index + 1}`,
        })),
      };
      const renderSet: MockOfficeRenderSet = {
        complete: true,
        page_count: pageCount,
        rendered_page_count: pageCount,
        evidence_ids: [evidenceId],
        evidence: [evidence],
      };
      revision.latest_render = evidence;
      revision.render_set = renderSet;
      revision.latest_review = null;
      revision.quality = {
        ...revision.quality,
        render_evidence_status: "available",
        visual_review_status: "pending",
      };
      updateOfficeRevision(project, revision);
      if (project.current_revision?.revision_id === revisionId) {
        project.render_evidence = [evidence];
        project.render_set = renderSet;
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(renderSet),
      });
    }

    const projectReviewMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/reviews$/.exec(
        pathname,
      );
    if (projectReviewMatch && method === "POST") {
      const projectId = decodeURIComponent(projectReviewMatch[1] ?? "");
      const revisionId = decodeURIComponent(projectReviewMatch[2] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const revision = project
        ? findOfficeRevision(project, revisionId)
        : undefined;
      if (!project || !revision) {
        return route.fulfill({ status: 404 });
      }
      const body = route.request().postDataJSON() as {
        status: "approved" | "changes_requested";
        evidence_ids: string[];
        note?: string;
      };
      const renderSet = officeRenderSet(project, revision);
      if (
        !renderSet.complete ||
        body.evidence_ids.join("|") !== renderSet.evidence_ids.join("|")
      ) {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Current render evidence required." }),
        });
      }
      const review: MockOfficeReview = {
        review_id: nextOfficeId("ofv"),
        revision_id: revisionId,
        created_at: "2026-07-17T11:05:00Z",
        status: body.status,
        note: body.note?.trim() ?? null,
        evidence_ids: [...renderSet.evidence_ids],
        page_count: renderSet.page_count,
        render_set_sha256: "8".repeat(64),
      };
      revision.latest_review = review;
      revision.quality = {
        ...revision.quality,
        visual_review_status: body.status,
      };
      updateOfficeRevision(project, revision);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(review),
      });
    }

    const projectFinalMatch = /^\/api\/office\/projects\/([^/]+)\/final$/.exec(
      pathname,
    );
    if (projectFinalMatch && method === "POST") {
      const projectId = decodeURIComponent(projectFinalMatch[1] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const body = route.request().postDataJSON() as {
        revision_id: string;
        review_id: string;
        expected_current_revision_id: string;
      };
      const revision = project
        ? findOfficeRevision(project, body.revision_id)
        : undefined;
      if (
        !project ||
        !revision ||
        project.current_revision?.revision_id !==
          body.expected_current_revision_id ||
        revision.latest_review?.review_id !== body.review_id ||
        revision.latest_review.status !== "approved"
      ) {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Current approved review required.",
          }),
        });
      }
      const selection = {
        selection_id: nextOfficeId("ofs"),
        revision_id: revision.revision_id,
        review_id: body.review_id,
        created_at: "2026-07-17T11:06:00Z",
        artifact: revision.artifact,
      };
      project.final_selection = selection;
      project.updated_at = selection.created_at;
      for (const item of project.revisions ?? []) {
        item.is_final = item.revision_id === revision.revision_id;
      }
      if (project.current_revision) {
        project.current_revision.is_final =
          project.current_revision.revision_id === revision.revision_id;
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(selection),
      });
    }

    const projectRestoreMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/restore$/.exec(
        pathname,
      );
    if (projectRestoreMatch && method === "POST") {
      const projectId = decodeURIComponent(projectRestoreMatch[1] ?? "");
      const targetRevisionId = decodeURIComponent(projectRestoreMatch[2] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const target = project
        ? findOfficeRevision(project, targetRevisionId)
        : undefined;
      const current = project?.current_revision;
      const body = route.request().postDataJSON() as {
        expected_current_revision_id: string;
      };
      if (
        !project ||
        !target ||
        !current ||
        current.revision_id !== body.expected_current_revision_id
      ) {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Current revision changed." }),
        });
      }
      const revisionId = nextOfficeId("ofr");
      const sequence =
        Math.max(
          0,
          ...(project.revisions ?? []).map((item) =>
            Number(item.sequence ?? 0),
          ),
        ) + 1;
      const operationId = `restore_revision_${sequence}`;
      const restoredRevision: MockOfficeRevision = {
        revision_id: revisionId,
        parent_revision_id: current.revision_id,
        sequence,
        kind: "restore",
        created_at: "2026-07-17T11:10:00Z",
        artifact: target.artifact,
        operation_count: 1,
        changed_target_count: 1,
        part_change_count: 1,
        relationship_change_count: 0,
        quality: {
          package_validation_status: "valid",
          preflight_status: "not_recorded",
          render_evidence_status: "not_available",
          visual_review_status: "not_performed",
        },
        latest_render: null,
        render_set: emptyOfficeRenderSet(),
        operation_receipt: {
          schema: "vassilflow.office.change-receipt.v1",
          format: project.format,
          status: "changed",
          source: current.artifact,
          result: target.artifact,
          operation_count: 1,
          applied_operation_ids: [operationId],
          operations: [
            {
              operation_id: operationId,
              position: 1,
              type: "restore_revision",
              match_count: 1,
              target_path_count: 1,
              target_paths: [`/project/revision[@id='${targetRevisionId}']`],
            },
          ],
          semantic_changes: {
            coverage: "partial",
            evaluated_target_count: 1,
            changed_target_count: 1,
            changed_target_paths: [
              `/project/revision[@id='${targetRevisionId}']`,
            ],
            semantic_delta_count: 1,
            semantic_deltas: [
              {
                path: "/project/current-revision",
                semantic_kind: "project_revision",
                property: "artifact_sha256",
                before: current.artifact?.sha256,
                after: target.artifact?.sha256,
              },
            ],
          },
          package_changes: {
            part_change_count: 1,
            parts: [],
            relationship_change_count: 0,
            relationships: [],
          },
        },
        restored_from_revision_id: targetRevisionId,
        latest_review: null,
        is_final: false,
      };
      project.current_revision = restoredRevision;
      project.render_evidence = [];
      project.render_set = emptyOfficeRenderSet();
      project.revisions = [restoredRevision, ...(project.revisions ?? [])];
      project.revision_count = sequence;
      project.updated_at = restoredRevision.created_at;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          project_id: projectId,
          revision_id: revisionId,
          parent_revision_id: current.revision_id,
          restored_from_revision_id: targetRevisionId,
          sequence,
          artifact: target.artifact,
          project_url: `/workspace/office/projects/${projectId}`,
        }),
      });
    }

    if (method !== "GET") return route.fallback();
    if (pathname === "/api/office/projects") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          projects: officeProjects.map(
            ({
              render_evidence: _renderEvidence,
              render_set: _renderSet,
              revisions: _revisions,
              ...project
            }) => project,
          ),
        }),
      });
    }

    const finalArtifactMatch =
      /^\/api\/office\/projects\/([^/]+)\/final\/artifact$/.exec(pathname);
    if (finalArtifactMatch) {
      const project = officeProjects.find(
        (item) => item.project_id === finalArtifactMatch[1],
      );
      return route.fulfill({
        status: project?.final_selection ? 200 : 404,
        contentType:
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers: {
          "Content-Disposition": "attachment; filename=final-revision.pptx",
        },
        body: Buffer.from("mock-final-pptx"),
      });
    }

    const revisionArtifactMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/artifact$/.exec(
        pathname,
      );
    if (revisionArtifactMatch) {
      const project = officeProjects.find(
        (item) => item.project_id === revisionArtifactMatch[1],
      );
      const revision = project
        ? findOfficeRevision(project, revisionArtifactMatch[2] ?? "")
        : undefined;
      return route.fulfill({
        status: revision ? 200 : 404,
        contentType:
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers: {
          "Content-Disposition": "attachment; filename=revision.pptx",
        },
        body: Buffer.from("mock-revision-pptx"),
      });
    }

    const previewMatch =
      /^\/api\/office\/projects\/([^/]+)\/renders\/([^/]+)\/pages\/(\d+)$/.exec(
        pathname,
      );
    if (previewMatch) {
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAYAAAA7KqwyAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAzSURBVChTY5D3q/xPCWYAEa8//SAKg9Q+ztaBY+oZQArGagC6Tcg2omOsBpCCh4EB6BgABGBPSggMnrAAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    }

    const selectionMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/selection$/.exec(
        pathname,
      );
    if (selectionMatch) {
      const projectId = decodeURIComponent(selectionMatch[1] ?? "");
      const revisionId = decodeURIComponent(selectionMatch[2] ?? "");
      const slide = Number(
        new URL(route.request().url()).searchParams.get("slide"),
      );
      const surface = officeSelectionSurfaces.find(
        (item) =>
          item.project_id === projectId &&
          item.revision_id === revisionId &&
          item.slide.index === slide,
      );
      return route.fulfill({
        status: surface ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          surface ?? { detail: "PowerPoint selection surface was not found." },
        ),
      });
    }

    const revisionComparisonMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)\/comparison$/.exec(
        pathname,
      );
    if (revisionComparisonMatch) {
      const projectId = decodeURIComponent(revisionComparisonMatch[1] ?? "");
      const revisionId = decodeURIComponent(revisionComparisonMatch[2] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const revision = project
        ? findOfficeRevision(project, revisionId)
        : undefined;
      const baseRevision =
        project && typeof revision?.parent_revision_id === "string"
          ? findOfficeRevision(project, revision.parent_revision_id)
          : undefined;
      if (
        !project ||
        !revision ||
        !baseRevision ||
        !revision.operation_receipt
      ) {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Comparison is not available." }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          project_id: projectId,
          format: project.format,
          base_revision: baseRevision,
          revision,
          operation_receipt: revision.operation_receipt,
          before_render: officeRenderSet(project, baseRevision),
          after_render: officeRenderSet(project, revision),
        }),
      });
    }

    const revisionDetailMatch =
      /^\/api\/office\/projects\/([^/]+)\/revisions\/([^/]+)$/.exec(pathname);
    if (revisionDetailMatch) {
      const projectId = decodeURIComponent(revisionDetailMatch[1] ?? "");
      const revisionId = decodeURIComponent(revisionDetailMatch[2] ?? "");
      const project = officeProjects.find(
        (item) => item.project_id === projectId,
      );
      const revision = project?.revisions?.find(
        (item) => item.revision_id === revisionId,
      );
      const isCurrent = project?.current_revision?.revision_id === revisionId;
      const renderEvidence = isCurrent
        ? (project?.render_evidence ?? [])
        : revision?.latest_render
          ? [revision.latest_render]
          : [];

      return route.fulfill({
        status: project && revision ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          project && revision
            ? {
                project_id: project.project_id,
                title: project.title,
                format: project.format,
                is_current: isCurrent,
                revision,
                render_evidence: renderEvidence,
                render_set: officeRenderSet(project, revision),
                operation_receipt: revision.operation_receipt ?? null,
                generation_receipt: revision.generation_receipt ?? null,
                generation_preflight: revision.generation_preflight ?? null,
              }
            : { detail: "Office revision resource was not found." },
        ),
      });
    }

    const revisionsMatch = /^\/api\/office\/projects\/([^/]+)\/revisions$/.exec(
      pathname,
    );
    if (revisionsMatch) {
      const project = officeProjects.find(
        (item) => item.project_id === revisionsMatch[1],
      );
      return route.fulfill({
        status: project ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          project
            ? {
                project_id: project.project_id,
                revisions: project.revisions ?? [],
              }
            : { detail: "Office project resource was not found." },
        ),
      });
    }

    const projectMatch = /^\/api\/office\/projects\/([^/]+)$/.exec(pathname);
    if (projectMatch) {
      const project = officeProjects.find(
        (item) => item.project_id === projectMatch[1],
      );
      const payload = project ? { ...project } : null;
      if (payload) {
        delete payload.revisions;
        payload.render_set = project?.current_revision
          ? officeRenderSet(project, project.current_revision)
          : emptyOfficeRenderSet();
      }
      return route.fulfill({
        status: project ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(
          payload ?? { detail: "Office project resource was not found." },
        ),
      });
    }

    return route.fulfill({ status: 404 });
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

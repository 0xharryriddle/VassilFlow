"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { getLangGraphBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";
import {
  loadStaticDemoThread,
  loadStaticDemoThreads,
  staticDemoThreadState,
} from "../threads/static-demo";
import type { AgentThreadState } from "../threads/types";

import { isStateChangingMethod, readCsrfCookie } from "./fetcher";
import { sanitizeRunStreamOptions } from "./stream-mode";

/**
 * Default SDK session credentials and a live ``X-CSRF-Token`` header only
 * inside the configured backend origin/path. Explicit caller settings win.
 *
 * Reading the cookie per-request (rather than baking it into the SDK's
 * ``defaultHeaders`` at construction) handles login / logout / password
 * change cookie rotation transparently. Both the ``/api/langgraph/*`` SDK
 * path and the direct REST endpoints in ``fetcher.ts:fetchWithAuth``
 * share :func:`readCsrfCookie` and :const:`STATE_CHANGING_METHODS` so
 * the contract stays in lockstep.
 */
export function authorizeSdkRequest(
  url: URL,
  init: RequestInit,
  apiUrl: string,
): RequestInit {
  const configured = new URL(apiUrl);
  const basePath = configured.pathname.replace(/\/+$/, "");
  if (
    url.origin !== configured.origin ||
    (url.pathname !== basePath && !url.pathname.startsWith(`${basePath}/`))
  ) {
    return init;
  }
  const authorized = { ...init, credentials: init.credentials ?? "include" };
  // Explicit omit/same-origin requests must not acquire ambient CSRF secrets
  // when their credential policy excludes cookies for this request.
  const sendsCookies =
    authorized.credentials === "include" ||
    (authorized.credentials === "same-origin" &&
      typeof window !== "undefined" &&
      url.origin === window.location.origin);
  if (!sendsCookies || !isStateChangingMethod(init.method ?? "GET"))
    return authorized;
  const token = readCsrfCookie();
  if (!token) return authorized;
  const headers = new Headers(init.headers);
  if (!headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", token);
  }
  return { ...authorized, headers };
}

function bindThreadCreateToAssistant(
  url: URL,
  init: RequestInit,
  assistantId?: string,
): RequestInit {
  const identity = assistantId?.trim();
  if (
    !identity ||
    (init.method ?? "GET").toUpperCase() !== "POST" ||
    !url.pathname.endsWith("/threads") ||
    typeof init.body !== "string"
  ) {
    return init;
  }

  try {
    const payload = JSON.parse(init.body) as unknown;
    if (
      typeof payload !== "object" ||
      payload === null ||
      Array.isArray(payload)
    ) {
      return init;
    }
    return {
      ...init,
      body: JSON.stringify({
        ...payload,
        assistant_id: identity,
      }),
    };
  } catch {
    return init;
  }
}

const TERMINAL_RUN_STATUSES = new Set([
  "success",
  "error",
  "timeout",
  "interrupted",
]);

function isRunConflictError(error: unknown, ...needles: string[]): boolean {
  const status =
    typeof error === "object" && error !== null
      ? Reflect.get(error, "status")
      : undefined;
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null
          ? String(Reflect.get(error, "message") ?? "")
          : "";

  return (
    (status === 409 || message.includes("HTTP 409")) &&
    needles.every((needle) => message.includes(needle))
  );
}

export function isInactiveRunStreamError(error: unknown): boolean {
  return isRunConflictError(
    error,
    "not active on this worker",
    "cannot be streamed",
  );
}

export function isRunNotCancellableError(error: unknown): boolean {
  return isRunConflictError(error, "is not cancellable");
}

async function shouldSkipReconnect(
  client: LangGraphClient,
  threadId: string,
  runId: string,
): Promise<boolean> {
  try {
    const run = await client.runs.get(threadId, runId);
    return TERMINAL_RUN_STATUSES.has(run.status);
  } catch {
    return false;
  }
}

export function clearReconnectRun(
  threadId: string | null | undefined,
  runId: string,
): void {
  if (typeof window === "undefined" || !threadId) return;

  const key = `lg:stream:${threadId}`;
  try {
    const storage = window.sessionStorage;
    if (storage.getItem(key) === runId) {
      storage.removeItem(key);
    }
  } catch {
    // Ignore storage access failures so reconnect cleanup never throws.
  }
}

function createCompatibleClient(
  isMock?: boolean,
  assistantId?: string,
): LangGraphClient {
  if (isStaticWebsiteOnly() && !isMock) {
    return createStaticClient();
  }

  const apiUrl = getLangGraphBaseURL(isMock);
  console.log(`Creating API client with base URL: ${apiUrl}`);
  const client = new LangGraphClient({
    apiUrl,
    onRequest: (url, init) =>
      bindThreadCreateToAssistant(
        url,
        authorizeSdkRequest(url, init, apiUrl),
        assistantId,
      ),
  });

  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  const originalCancel = client.runs.cancel.bind(client.runs);
  client.runs.cancel = (async (threadId, runId, wait, action, options) => {
    try {
      return await originalCancel(threadId, runId, wait, action, options);
    } catch (error) {
      if (isRunNotCancellableError(error)) {
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  }) as typeof client.runs.cancel;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = async function* (threadId, runId, options) {
    if (threadId && (await shouldSkipReconnect(client, threadId, runId))) {
      clearReconnectRun(threadId, runId);
      return;
    }
    try {
      yield* originalJoinStream(
        threadId,
        runId,
        sanitizeRunStreamOptions(options),
      );
    } catch (error) {
      if (isInactiveRunStreamError(error)) {
        clearReconnectRun(threadId, runId);
        return;
      }
      throw error;
    }
  } as typeof client.runs.joinStream;

  return client;
}

function createStaticClient(): LangGraphClient {
  const apiUrl =
    typeof window === "undefined"
      ? "http://localhost:3000"
      : window.location.origin;
  const client = new LangGraphClient({ apiUrl });

  client.threads.search = (async (query) => {
    return loadStaticDemoThreads(query);
  }) as typeof client.threads.search;

  client.threads.get = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.get;

  client.threads.getState = (async (threadId) => {
    return staticDemoThreadState(await loadStaticDemoThread(threadId));
  }) as typeof client.threads.getState;

  client.threads.getHistory = (async (threadId) => {
    return [staticDemoThreadState(await loadStaticDemoThread(threadId))];
  }) as typeof client.threads.getHistory;

  client.threads.update = (async (threadId) => {
    return loadStaticDemoThread(threadId);
  }) as typeof client.threads.update;

  client.runs.list = (async () => []) as typeof client.runs.list;
  client.runs.stream = async function* () {
    /* empty */
  } as typeof client.runs.stream;
  client.runs.joinStream = async function* () {
    /* empty */
  } as typeof client.runs.joinStream;

  return client as LangGraphClient<AgentThreadState>;
}

const _clients = new Map<string, LangGraphClient>();
export function getAPIClient(
  isMock?: boolean,
  assistantId?: string,
): LangGraphClient {
  const scopedAssistantId = assistantId?.trim() ?? "unbound";
  const cacheKey = `${isMock ? "mock" : "default"}:${scopedAssistantId}`;
  let client = _clients.get(cacheKey);

  if (!client) {
    client = createCompatibleClient(isMock, assistantId);
    _clients.set(cacheKey, client);
  }

  return client;
}

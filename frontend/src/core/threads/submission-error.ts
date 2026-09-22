import type { Message } from "@langchain/langgraph-sdk";

export type SubmissionErrorKind =
  | "authentication"
  | "connection"
  | "rateLimit"
  | "unknown";

// Backend exceptions may contain model configuration, credentials, or a
// traceback. Inspect them only to select a fixed, localized UI message.
export function classifySubmissionError(error: unknown): SubmissionErrorKind {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : typeof error === "object" && error !== null
          ? String(
              Reflect.get(error, "message") ??
                Reflect.get(error, "error") ??
                "",
            )
          : "";
  const status =
    typeof error === "object" && error !== null
      ? Reflect.get(error, "status")
      : undefined;
  if (
    status === 401 ||
    status === 403 ||
    /credential|api.?key|unauthorized|authentication/i.test(message)
  ) {
    return "authentication";
  }
  if (status === 429 || /rate.?limit|too many requests/i.test(message)) {
    return "rateLimit";
  }
  if (
    /fetch failed|failed to fetch|network|connection|timeout|timed out/i.test(
      message,
    )
  ) {
    return "connection";
  }
  return "unknown";
}

export function preserveFailedSubmission(messages: Message[]): Message[] {
  // Keep the local human copy until the normal checkpoint reconciliation
  // replaces it. Transient upload/task indicators must stop on failure.
  return messages.filter((message) => message.type === "human");
}

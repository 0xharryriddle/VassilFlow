import { fetch } from "@/core/api/fetcher";

import type { RunMessage } from "./types";

export type RunMessagesPageResponse = {
  data: RunMessage[];
  has_more?: boolean;
  hasMore?: boolean;
};

export async function fetchRunMessagesPage(
  url: string,
  signal?: AbortSignal,
): Promise<RunMessagesPageResponse> {
  const response = await fetch(url, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Thread history request failed (HTTP ${response.status}).`);
  }
  const page: unknown = await response.json();
  signal?.throwIfAborted();
  if (
    typeof page !== "object" ||
    page === null ||
    !Array.isArray(Reflect.get(page, "data"))
  ) {
    throw new Error("Invalid thread history response.");
  }
  for (const key of ["has_more", "hasMore"] as const) {
    if (
      Reflect.get(page, key) !== undefined &&
      typeof Reflect.get(page, key) !== "boolean"
    ) {
      throw new Error("Invalid thread history response.");
    }
  }
  for (const row of Reflect.get(page, "data") as unknown[]) {
    if (typeof row !== "object" || row === null)
      throw new Error("Invalid thread history response.");
    const content: unknown = Reflect.get(row, "content");
    const metadata: unknown = Reflect.get(row, "metadata");
    if (
      typeof content !== "object" ||
      content === null ||
      typeof Reflect.get(content, "type") !== "string" ||
      typeof metadata !== "object" ||
      metadata === null ||
      (Reflect.get(metadata, "caller") !== undefined &&
        typeof Reflect.get(metadata, "caller") !== "string")
    ) {
      throw new Error("Invalid thread history response.");
    }
  }
  return page as RunMessagesPageResponse;
}

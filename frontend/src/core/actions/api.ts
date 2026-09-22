import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ActionsResponse, ProvenanceAction } from "./types";

type ActionListOptions = {
  limit?: number;
  operation?: string;
  resourceKind?: string;
  resourceId?: string;
};

function actionApiURL(path: string): string {
  return `${getBackendBaseURL()}${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      payload?.detail ??
        `Failed to load action provenance: ${response.statusText}`,
    );
  }
  return response.json() as Promise<T>;
}

export async function listActions(
  options: ActionListOptions = {},
): Promise<ActionsResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 100),
  });
  if (options.operation) {
    params.set("operation", options.operation);
  }
  if (options.resourceKind) {
    params.set("resource_kind", options.resourceKind);
  }
  if (options.resourceId) {
    params.set("resource_id", options.resourceId);
  }
  const response = await fetch(actionApiURL(`/api/actions?${params}`));
  return readJson<ActionsResponse>(response);
}

export async function getAction(actionId: string): Promise<ProvenanceAction> {
  const response = await fetch(
    actionApiURL(`/api/actions/${encodeURIComponent(actionId)}`),
  );
  return readJson<ProvenanceAction>(response);
}

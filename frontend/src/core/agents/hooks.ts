import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import {
  createAgent,
  deleteAgent,
  listAgentCatalog,
  updateAgent,
} from "./api";
import {
  AGENT_PINS_CHANGED_EVENT,
  getPinnedAgentIdsKey,
  loadPinnedAgentIds,
  normalizePinnedAgentIds,
  savePinnedAgentIds,
} from "./catalog";
import type { CreateAgentRequest, UpdateAgentRequest } from "./types";

export function useAgents() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgentCatalog(),
  });
  return {
    agents: data?.agents ?? [],
    customAgentManagementEnabled:
      data?.custom_agent_management_enabled ?? false,
    isLoading,
    error,
  };
}

export function useAgentPins(userId: string) {
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);
  const storageKey = getPinnedAgentIdsKey(userId);

  useEffect(() => {
    setPinnedIds(loadPinnedAgentIds(userId));

    const handleStorage = (event: StorageEvent) => {
      if (event.key === storageKey) {
        setPinnedIds(loadPinnedAgentIds(userId));
      }
    };
    const handleLocalChange = (event: Event) => {
      const detail = (event as CustomEvent<{ key?: unknown; ids?: unknown }>)
        .detail;
      if (detail?.key === storageKey) {
        setPinnedIds(normalizePinnedAgentIds(detail.ids));
      }
    };

    window.addEventListener("storage", handleStorage);
    window.addEventListener(AGENT_PINS_CHANGED_EVENT, handleLocalChange);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener(AGENT_PINS_CHANGED_EVENT, handleLocalChange);
    };
  }, [storageKey, userId]);

  const updatePinnedIds = useCallback(
    (ids: string[]) => {
      const normalized = normalizePinnedAgentIds(ids);
      setPinnedIds(normalized);
      savePinnedAgentIds(userId, normalized);
    },
    [userId],
  );

  return { pinnedIds, updatePinnedIds };
}

export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgentCatalog(),
    select: (catalog) =>
      catalog.agents.find((agent) => agent.name === name) ?? null,
    enabled: !!name,
  });
  return { agent: data ?? null, isLoading, error };
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
    },
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });
}

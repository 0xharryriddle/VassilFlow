"use client";

import { BotIcon, PinIcon, PlusIcon, SearchIcon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  filterAgentCatalog,
  partitionPinnedAgents,
  retainAvailablePinnedAgentIds,
  toggleAgentPin,
  useAgentPins,
  useAgents,
} from "@/core/agents";
import type {
  Agent,
  AgentCategory,
  AgentCategoryFilter,
  AgentOrigin,
  AgentOriginFilter,
} from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { AgentCard } from "./agent-card";
import { AgentProfileSheet } from "./agent-profile-sheet";

const ORIGIN_ORDER: AgentOrigin[] = ["builtin", "personal", "team"];

function AgentGrid({
  agents,
  pinnedIds,
  onTogglePin,
  onViewDetails,
}: {
  agents: Agent[];
  pinnedIds: Set<string>;
  onTogglePin: (agent: Agent) => void;
  onViewDetails: (agent: Agent) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {agents.map((agent) => (
        <AgentCard
          key={agent.product.id}
          agent={agent}
          pinned={pinnedIds.has(agent.product.id)}
          onTogglePin={onTogglePin}
          onViewDetails={onViewDetails}
        />
      ))}
    </div>
  );
}

export function AgentGallery() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { agents, customAgentManagementEnabled, isLoading } = useAgents();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [origin, setOrigin] = useState<AgentOriginFilter>("all");
  const [category, setCategory] = useState<AgentCategoryFilter>("all");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const pinOwnerId = user?.id ?? "anonymous";
  const { pinnedIds, updatePinnedIds } = useAgentPins(pinOwnerId);

  const availableOrigins = useMemo(
    () => new Set(agents.map((agent) => agent.product.origin)),
    [agents],
  );
  useEffect(() => {
    if (origin !== "all" && !availableOrigins.has(origin)) {
      setOrigin("all");
    }
  }, [availableOrigins, origin]);
  const availableCategories = useMemo(
    () => new Set(agents.map((agent) => agent.product.category)),
    [agents],
  );
  useEffect(() => {
    if (category !== "all" && !availableCategories.has(category)) {
      setCategory("all");
    }
  }, [availableCategories, category]);
  const filteredAgents = useMemo(
    () => filterAgentCatalog(agents, { query, origin, category }),
    [agents, category, origin, query],
  );
  const activePinnedIds = useMemo(
    () => retainAvailablePinnedAgentIds(pinnedIds, agents),
    [agents, pinnedIds],
  );
  const catalog = useMemo(
    () => partitionPinnedAgents(filteredAgents, activePinnedIds),
    [activePinnedIds, filteredAgents],
  );
  const pinnedIdSet = useMemo(
    () => new Set(activePinnedIds),
    [activePinnedIds],
  );
  const originLabels: Record<AgentOriginFilter, string> = {
    all: t.agents.filterAll,
    builtin: t.agents.originBuiltin,
    personal: t.agents.originPersonal,
    team: t.agents.originTeam,
  };
  const categoryLabels: Record<AgentCategoryFilter, string> = {
    all: t.agents.categoryAll,
    general: t.agents.categoryGeneral,
    create: t.agents.categoryCreate,
    research: t.agents.categoryResearch,
    build: t.agents.categoryBuild,
    analyze: t.agents.categoryAnalyze,
    automate: t.agents.categoryAutomate,
    custom: t.agents.categoryCustom,
  };

  const handleNewAgent = () => {
    router.push("/workspace/agents/new");
  };

  const handleTogglePin = (agent: Agent) => {
    const result = toggleAgentPin(activePinnedIds, agent.product.id);
    if (!result.changed && result.reason === "limit") {
      toast.error(t.agents.pinLimitReached);
      return;
    }
    updatePinnedIds(result.ids);
  };

  return (
    <>
      <div className="flex size-full flex-col">
        <div className="flex flex-col items-stretch justify-between gap-3 border-b px-4 py-4 sm:flex-row sm:items-center sm:px-6">
          <div>
            <h1 className="text-xl font-semibold">{t.agents.title}</h1>
            <p className="text-muted-foreground mt-0.5 text-sm">
              {t.agents.description}
            </p>
          </div>
          {customAgentManagementEnabled && (
            <Button onClick={handleNewAgent}>
              <PlusIcon className="mr-1.5 h-4 w-4" />
              {t.agents.newAgent}
            </Button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
          {isLoading ? (
            <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
              {t.common.loading}
            </div>
          ) : agents.length === 0 ? (
            <Empty className="h-64 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BotIcon />
                </EmptyMedia>
                <EmptyTitle>{t.agents.emptyTitle}</EmptyTitle>
                <EmptyDescription>{t.agents.emptyDescription}</EmptyDescription>
              </EmptyHeader>
              {customAgentManagementEnabled && (
                <EmptyContent>
                  <Button variant="outline" onClick={handleNewAgent}>
                    <PlusIcon />
                    {t.agents.newAgent}
                  </Button>
                </EmptyContent>
              )}
            </Empty>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="relative w-full md:max-w-sm">
                  <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
                  <Input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t.agents.searchPlaceholder}
                    aria-label={t.agents.searchPlaceholder}
                    className="pl-9"
                  />
                </div>
                <div className="flex max-w-full flex-wrap items-center gap-2 self-start md:justify-end md:self-auto">
                  {availableOrigins.size > 1 && (
                    <ToggleGroup
                      type="single"
                      variant="outline"
                      size="sm"
                      value={origin}
                      onValueChange={(value) => {
                        if (value) setOrigin(value as AgentOriginFilter);
                      }}
                      aria-label={t.agents.filterAll}
                      className="max-w-full flex-wrap"
                    >
                      {(["all", ...ORIGIN_ORDER] as AgentOriginFilter[])
                        .filter(
                          (value) =>
                            value === "all" || availableOrigins.has(value),
                        )
                        .map((value) => (
                          <ToggleGroupItem key={value} value={value}>
                            {originLabels[value]}
                          </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                  )}
                  {availableCategories.size > 1 && (
                    <Select
                      value={category}
                      onValueChange={(value) =>
                        setCategory(value as AgentCategoryFilter)
                      }
                    >
                      <SelectTrigger
                        size="sm"
                        className="max-w-48"
                        aria-label={t.agents.categoryAll}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent align="end">
                        <SelectItem value="all">
                          {categoryLabels.all}
                        </SelectItem>
                        {Array.from(availableCategories)
                          .sort()
                          .map((value: AgentCategory) => (
                            <SelectItem key={value} value={value}>
                              {categoryLabels[value]}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </div>

              <div className="text-muted-foreground text-sm">
                {t.agents.resultCount(filteredAgents.length)}
              </div>

              {filteredAgents.length === 0 ? (
                <Empty className="h-56 border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <SearchIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t.agents.noMatchesTitle}</EmptyTitle>
                    <EmptyDescription>
                      {t.agents.noMatchesDescription}
                    </EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setQuery("");
                        setOrigin("all");
                        setCategory("all");
                      }}
                    >
                      <XIcon />
                      {t.agents.clearSearch}
                    </Button>
                  </EmptyContent>
                </Empty>
              ) : (
                <>
                  {catalog.pinned.length > 0 && (
                    <section aria-labelledby="pinned-agents-heading">
                      <div className="mb-3 flex items-center gap-2">
                        <PinIcon className="text-muted-foreground h-4 w-4" />
                        <h2
                          id="pinned-agents-heading"
                          className="text-sm font-medium"
                        >
                          {t.agents.pinned}
                        </h2>
                      </div>
                      <AgentGrid
                        agents={catalog.pinned}
                        pinnedIds={pinnedIdSet}
                        onTogglePin={handleTogglePin}
                        onViewDetails={setSelectedAgent}
                      />
                    </section>
                  )}

                  {catalog.others.length > 0 && (
                    <section aria-labelledby="all-agents-heading">
                      <h2
                        id="all-agents-heading"
                        className="mb-3 text-sm font-medium"
                      >
                        {t.agents.allAgents}
                      </h2>
                      <AgentGrid
                        agents={catalog.others}
                        pinnedIds={pinnedIdSet}
                        onTogglePin={handleTogglePin}
                        onViewDetails={setSelectedAgent}
                      />
                    </section>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
      <AgentProfileSheet
        agent={selectedAgent}
        open={selectedAgent !== null}
        pinned={
          selectedAgent !== null && pinnedIdSet.has(selectedAgent.product.id)
        }
        onOpenChange={(open) => {
          if (!open) setSelectedAgent(null);
        }}
        onTogglePin={handleTogglePin}
      />
    </>
  );
}

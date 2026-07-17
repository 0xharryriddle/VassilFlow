"use client";

import {
  FolderKanbanIcon,
  MessageSquareIcon,
  PinOffIcon,
  PinIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { iconForAgent, isSafeAgentLaunchPath } from "@/core/agents";
import type {
  Agent,
  AgentCategory,
  AgentDataAccess,
  AgentOrigin,
} from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

interface AgentProfileSheetProps {
  agent: Agent | null;
  open: boolean;
  pinned: boolean;
  onOpenChange: (open: boolean) => void;
  onTogglePin: (agent: Agent) => void;
}

function BadgeList({ values }: { values: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <Badge key={value} variant="secondary" className="max-w-full truncate">
          {value}
        </Badge>
      ))}
    </div>
  );
}

export function AgentProfileSheet({
  agent,
  open,
  pinned,
  onOpenChange,
  onTogglePin,
}: AgentProfileSheetProps) {
  const { t } = useI18n();
  const router = useRouter();

  if (!agent) {
    return null;
  }

  const product = agent.product;
  const AgentIcon = iconForAgent(product.icon);
  const LaunchIcon =
    product.launch.kind === "project" ? FolderKanbanIcon : MessageSquareIcon;
  const launchLabel =
    product.launch.kind === "project"
      ? t.agents.launchProject
      : t.agents.launchChat;
  const originLabels: Record<AgentOrigin, string> = {
    builtin: t.agents.originBuiltin,
    personal: t.agents.originPersonal,
    team: t.agents.originTeam,
  };
  const categoryLabels: Record<AgentCategory, string> = {
    general: t.agents.categoryGeneral,
    create: t.agents.categoryCreate,
    research: t.agents.categoryResearch,
    build: t.agents.categoryBuild,
    analyze: t.agents.categoryAnalyze,
    automate: t.agents.categoryAutomate,
    custom: t.agents.categoryCustom,
  };
  const dataAccessLabels: Record<AgentDataAccess, string> = {
    thread_uploads: t.agents.dataThreadUploads,
    thread_workspace: t.agents.dataThreadWorkspace,
    thread_outputs: t.agents.dataThreadOutputs,
  };

  const handleLaunch = () => {
    if (
      product.status !== "available" ||
      !isSafeAgentLaunchPath(product.launch.path)
    ) {
      toast.error(t.agents.launchUnavailable);
      return;
    }
    onOpenChange(false);
    router.push(product.launch.path);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[min(92vw,440px)] gap-0 sm:max-w-[440px]">
        <SheetHeader className="border-b px-5 py-5 pr-12">
          <div className="flex items-start gap-3">
            <div className="bg-primary/10 text-primary flex size-11 shrink-0 items-center justify-center rounded-md">
              <AgentIcon className="size-5" />
            </div>
            <div className="min-w-0">
              <SheetTitle className="truncate text-lg">
                {product.display_name}
              </SheetTitle>
              <SheetDescription className="mt-1 text-pretty">
                {agent.description}
              </SheetDescription>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{originLabels[product.origin]}</Badge>
                <Badge variant="secondary">
                  <LaunchIcon />
                  {launchLabel}
                </Badge>
              </div>
            </div>
          </div>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="space-y-5">
            {product.status === "unavailable" && (
              <section className="border-destructive/40 bg-destructive/5 rounded-md border p-3">
                <h3 className="text-destructive text-sm font-medium">
                  {t.agents.unavailableRequirements}
                </h3>
                <div className="mt-2">
                  <BadgeList values={product.missing_requirements} />
                </div>
              </section>
            )}

            <section>
              <h3 className="text-sm font-medium">
                {t.agents.profileOverview}
              </h3>
              <dl className="mt-3 grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <dt className="text-muted-foreground">
                  {t.agents.profileCategory}
                </dt>
                <dd>{categoryLabels[product.category]}</dd>
                <dt className="text-muted-foreground">
                  {t.agents.profileModel}
                </dt>
                <dd>{agent.model ?? t.agents.workspaceDefault}</dd>
              </dl>
            </section>

            <Separator />

            <section>
              <h3 className="text-sm font-medium">
                {t.agents.profileCapabilities}
              </h3>
              <div className="mt-3 space-y-3 text-sm">
                {product.required_tools.length > 0 && (
                  <BadgeList values={product.required_tools} />
                )}
                {agent.tool_groups && agent.tool_groups.length > 0 && (
                  <div>
                    <div className="text-muted-foreground mb-1.5 text-xs">
                      {t.agents.profileToolGroups}
                    </div>
                    <BadgeList values={agent.tool_groups} />
                  </div>
                )}
                {product.required_tools.length === 0 &&
                  (!agent.tool_groups || agent.tool_groups.length === 0) && (
                    <p className="text-muted-foreground">
                      {t.agents.noSpecificCapabilities}
                    </p>
                  )}
              </div>
            </section>

            <section>
              <h3 className="text-sm font-medium">{t.agents.profileSkills}</h3>
              <div className="mt-2 text-sm">
                {agent.skills === null ? (
                  <span className="text-muted-foreground">
                    {t.agents.workspaceDefault}
                  </span>
                ) : agent.skills.length > 0 ? (
                  <BadgeList values={agent.skills} />
                ) : (
                  <span className="text-muted-foreground">
                    {t.agents.noDedicatedSkills}
                  </span>
                )}
              </div>
            </section>

            {product.data_access.length > 0 && (
              <section>
                <h3 className="text-sm font-medium">
                  {t.agents.profileDataAccess}
                </h3>
                <ul className="text-muted-foreground mt-2 space-y-1.5 text-sm">
                  {product.data_access.map((access) => (
                    <li key={access} className="flex gap-2">
                      <span aria-hidden="true">-</span>
                      <span>{dataAccessLabels[access]}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {product.starter_prompts.length > 0 && (
              <section>
                <h3 className="text-sm font-medium">
                  {t.agents.profileStarters}
                </h3>
                <ul className="mt-2 space-y-2 text-sm">
                  {product.starter_prompts.map((prompt) => (
                    <li key={prompt} className="border-l-2 pl-3 text-pretty">
                      {prompt}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>

        <SheetFooter className="border-t px-5 py-4 sm:flex-row">
          <Button
            variant="outline"
            onClick={() => onTogglePin(agent)}
            className="sm:flex-1"
          >
            {pinned ? <PinOffIcon /> : <PinIcon />}
            {pinned
              ? t.agents.unpinAgent(product.display_name)
              : t.agents.pinAgent(product.display_name)}
          </Button>
          <Button
            onClick={handleLaunch}
            disabled={product.status !== "available"}
            className="sm:flex-1"
          >
            <LaunchIcon />
            {launchLabel}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

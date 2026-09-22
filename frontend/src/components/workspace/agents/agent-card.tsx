"use client";

import {
  FolderKanbanIcon,
  InfoIcon,
  MessageSquareIcon,
  PinIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type ReactElement, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  iconForAgent,
  isSafeAgentLaunchPath,
  useDeleteAgent,
} from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface AgentCardProps {
  agent: Agent;
  pinned: boolean;
  onTogglePin: (agent: Agent) => void;
  onViewDetails: (agent: Agent) => void;
}

/**
 * Reveals the full text in a tooltip ONLY when its trigger is actually clipped.
 * Clipping is measured on pointer enter against the trigger's own box, covering
 * both single-line `truncate` (width) and multi-line `line-clamp` (height), so
 * untruncated content never pops a redundant tooltip.
 */
function TruncatedTooltip({
  text,
  children,
}: {
  text: string;
  children: ReactElement;
}) {
  const [truncated, setTruncated] = useState(false);
  return (
    <Tooltip>
      <TooltipTrigger
        asChild
        onPointerEnter={(e) => {
          const el = e.currentTarget;
          setTruncated(
            el.scrollWidth > el.clientWidth ||
              el.scrollHeight > el.clientHeight,
          );
        }}
      >
        {children}
      </TooltipTrigger>
      {truncated && (
        <TooltipContent className="max-w-xs text-wrap break-words">
          {text}
        </TooltipContent>
      )}
    </Tooltip>
  );
}

export function AgentCard({
  agent,
  pinned,
  onTogglePin,
  onViewDetails,
}: AgentCardProps) {
  const { t } = useI18n();
  const router = useRouter();
  const deleteAgent = useDeleteAgent();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const displayName = agent.product.display_name;
  const AgentIcon = iconForAgent(agent.product.icon);
  const originLabel =
    agent.product.origin === "builtin"
      ? t.agents.originBuiltin
      : agent.product.origin === "team"
        ? t.agents.originTeam
        : t.agents.originPersonal;
  const launchLabel =
    agent.product.launch.kind === "project"
      ? t.agents.launchProject
      : t.agents.launchChat;
  const LaunchIcon =
    agent.product.launch.kind === "project"
      ? FolderKanbanIcon
      : MessageSquareIcon;

  function handleLaunch() {
    if (
      agent.product.status === "unavailable" ||
      !isSafeAgentLaunchPath(agent.product.launch.path)
    ) {
      toast.error(t.agents.launchUnavailable);
      return;
    }
    router.push(agent.product.launch.path);
  }

  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
      setDeleteOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <Card className="group h-full min-h-52 gap-0 rounded-lg py-0 transition-shadow hover:shadow-md">
        <CardHeader className="px-4 pt-4 pb-3">
          <div className="flex min-w-0 items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
                <AgentIcon className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <TruncatedTooltip text={displayName}>
                  <CardTitle className="truncate text-base">
                    {displayName}
                  </CardTitle>
                </TruncatedTooltip>
                <div className="mt-1 flex min-w-0 flex-wrap gap-1">
                  <Badge variant="outline" className="max-w-full truncate">
                    {originLabel}
                  </Badge>
                  <Badge variant="secondary">
                    <LaunchIcon />
                    {launchLabel}
                  </Badge>
                  {agent.product.status === "degraded" && (
                    <Badge
                      variant="outline"
                      className="border-amber-500/50 text-amber-700 dark:text-amber-300"
                    >
                      <TriangleAlertIcon />
                      {t.agents.statusDegraded}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            <div className="flex shrink-0 gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 shrink-0"
                    onClick={() => onViewDetails(agent)}
                    aria-label={t.agents.viewDetails(displayName)}
                  >
                    <InfoIcon className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {t.agents.viewDetails(displayName)}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 shrink-0"
                    onClick={() => onTogglePin(agent)}
                    aria-label={
                      pinned
                        ? t.agents.unpinAgent(displayName)
                        : t.agents.pinAgent(displayName)
                    }
                    aria-pressed={pinned}
                  >
                    <PinIcon
                      className={cn("h-4 w-4", pinned && "fill-current")}
                    />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {pinned
                    ? t.agents.unpinAgent(displayName)
                    : t.agents.pinAgent(displayName)}
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
          {agent.description && (
            <TruncatedTooltip text={agent.description}>
              <CardDescription className="mt-2 line-clamp-2 min-h-10 text-sm">
                {agent.description}
              </CardDescription>
            </TruncatedTooltip>
          )}
          {!agent.description && <div className="mt-2 min-h-10" />}
        </CardHeader>

        <CardFooter className="mt-auto flex items-center justify-between gap-2 border-t px-4 py-3">
          <Button
            size="sm"
            className="flex-1"
            onClick={handleLaunch}
            disabled={agent.product.status === "unavailable"}
          >
            <LaunchIcon className="mr-1.5 h-3.5 w-3.5" />
            {launchLabel}
          </Button>
          <div className="flex gap-1">
            {agent.product.management.can_delete && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
                    onClick={() => setDeleteOpen(true)}
                    aria-label={t.agents.delete}
                  >
                    <Trash2Icon className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t.agents.delete}</TooltipContent>
              </Tooltip>
            )}
          </div>
        </CardFooter>
      </Card>

      {/* Delete Confirm */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.agents.delete}</DialogTitle>
            <DialogDescription>{t.agents.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteAgent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAgent.isPending}
            >
              {deleteAgent.isPending ? t.common.loading : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

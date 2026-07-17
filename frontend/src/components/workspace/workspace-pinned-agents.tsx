"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import {
  iconForAgent,
  isSafeAgentLaunchPath,
  partitionPinnedAgents,
  retainAvailablePinnedAgentIds,
  useAgentPins,
  useAgents,
} from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspacePinnedAgents() {
  const { t } = useI18n();
  const { user } = useAuth();
  const pathname = usePathname();
  const { agents } = useAgents();
  const { pinnedIds } = useAgentPins(user?.id ?? "anonymous");
  const pinnedAgents = useMemo(() => {
    const activeIds = retainAvailablePinnedAgentIds(pinnedIds, agents);
    return partitionPinnedAgents(agents, activeIds).pinned;
  }, [agents, pinnedIds]);

  if (pinnedAgents.length === 0) {
    return null;
  }

  return (
    <SidebarGroup className="py-1">
      <SidebarGroupLabel>{t.agents.pinned}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {pinnedAgents.map((agent) => {
            const product = agent.product;
            const AgentIcon = iconForAgent(product.icon);
            const launchable =
              product.status === "available" &&
              isSafeAgentLaunchPath(product.launch.path);
            const activePrefix = `/workspace/agents/${encodeURIComponent(agent.name)}/`;
            const content = (
              <>
                <AgentIcon />
                <span>{product.display_name}</span>
              </>
            );

            return (
              <SidebarMenuItem key={product.id}>
                {launchable ? (
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(activePrefix)}
                    tooltip={product.display_name}
                  >
                    <Link
                      className="text-muted-foreground"
                      href={product.launch.path}
                    >
                      {content}
                    </Link>
                  </SidebarMenuButton>
                ) : (
                  <SidebarMenuButton
                    disabled
                    tooltip={t.agents.launchUnavailable}
                  >
                    {content}
                  </SidebarMenuButton>
                )}
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

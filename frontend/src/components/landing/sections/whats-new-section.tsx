"use client";

import {
  BoxesIcon,
  CircuitBoardIcon,
  FingerprintIcon,
  MemoryStickIcon,
  RouteIcon,
  ShieldCheckIcon,
} from "lucide-react";

import { APP_BRAND_NAME } from "@/core/brand";
import { cn } from "@/lib/utils";

import { Section } from "../section";

const foundations = [
  {
    icon: FingerprintIcon,
    label: "Runtime Identity",
    title: "VassilFlow-native config",
    description:
      "Runtime state, database paths, gateway headers, and frontend storage all use the VassilFlow namespace.",
  },
  {
    icon: BoxesIcon,
    label: "Skills",
    title: "Category-safe skill ids",
    description:
      "Public and custom skills can share a name because the harness addresses them as category-qualified capabilities.",
  },
  {
    icon: RouteIcon,
    label: "Subagents",
    title: "Composable delegation",
    description:
      "A lead agent can route work to focused subagents without forcing every workflow into a fixed graph.",
  },
  {
    icon: ShieldCheckIcon,
    label: "Sandbox",
    title: "Controlled execution",
    description:
      "Files, commands, and artifacts stay inside a configured execution boundary.",
  },
  {
    icon: MemoryStickIcon,
    label: "Context",
    title: "Memory-aware continuity",
    description:
      "The runtime can retain useful context while keeping long-horizon work manageable.",
  },
  {
    icon: CircuitBoardIcon,
    label: "Harness",
    title: "Provider-flexible core",
    description:
      "Models, tools, channels, policies, and storage can be composed for different agent products.",
  },
];

export function WhatsNewSection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("bg-[#07090b] px-4", className)}
      title={`${APP_BRAND_NAME} Foundation`}
      subtitle={`${APP_BRAND_NAME} now presents itself as a stand-alone superagent harness with its own runtime, UI, and extension model.`}
    >
      <div className="container-md mx-auto mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {foundations.map((item) => {
          const Icon = item.icon;
          return (
            <article
              key={item.title}
              className="rounded-md border border-white/10 bg-white/[0.035] p-5"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-sm bg-amber-200/10 text-amber-100">
                  <Icon className="size-5" />
                </div>
                <span className="text-xs font-semibold tracking-[0.2em] text-white/45 uppercase">
                  {item.label}
                </span>
              </div>
              <h3 className="mt-8 text-xl font-semibold text-white">
                {item.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-white/60">
                {item.description}
              </p>
            </article>
          );
        })}
      </div>
    </Section>
  );
}

"use client";

import {
  CircuitBoardIcon,
  DatabaseIcon,
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
    label: "identity",
    title: "Canonical runtime namespace",
    description:
      "Runtime state, database paths, gateway headers, and frontend storage resolve through VassilFlow names.",
  },
  {
    icon: DatabaseIcon,
    label: "state",
    title: "Durable workspace continuity",
    description:
      "Threads, files, memory, and artifacts stay connected across long-running work.",
  },
  {
    icon: RouteIcon,
    label: "routing",
    title: "Composable delegation",
    description:
      "Lead agents can route work to focused skills and subagents without forcing every product into one graph.",
  },
  {
    icon: ShieldCheckIcon,
    label: "policy",
    title: "Bounded tool execution",
    description:
      "Filesystem, shell, browser, and MCP access stay inside configured runtime boundaries.",
  },
  {
    icon: MemoryStickIcon,
    label: "context",
    title: "Memory-aware runs",
    description:
      "The harness keeps useful context available while preserving explicit thread ownership.",
  },
  {
    icon: CircuitBoardIcon,
    label: "core",
    title: "Provider-flexible harness",
    description:
      "Models, tools, channels, policies, storage, and UI surfaces can be composed for different agent products.",
  },
];

export function WhatsNewSection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("bg-[#07090b]", className)}
      title={`${APP_BRAND_NAME} Runtime Foundation`}
      subtitle="A standalone base for agent products that need traceable runs, durable state, controlled execution, and extensible skills."
    >
      <div className="container-md mx-auto mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {foundations.map((item) => {
          const Icon = item.icon;
          return (
            <article
              key={item.title}
              className="border border-white/10 bg-white/[0.035] p-5"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-sm bg-amber-200/10 text-amber-100">
                  <Icon className="size-5" />
                </div>
                <span className="font-mono text-xs text-white/44">
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

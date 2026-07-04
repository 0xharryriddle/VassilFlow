import {
  DatabaseIcon,
  FileCheck2Icon,
  NetworkIcon,
  PanelsTopLeftIcon,
  SearchCheckIcon,
  WorkflowIcon,
} from "lucide-react";

import { APP_BRAND_NAME } from "@/core/brand";
import { cn } from "@/lib/utils";

import { Section } from "../section";

const blueprints = [
  {
    icon: SearchCheckIcon,
    title: "Evidence Research",
    description:
      "Plan source collection, verify findings, and turn research into a structured artifact.",
  },
  {
    icon: DatabaseIcon,
    title: "Data Workspace",
    description:
      "Load files, run analysis, generate charts, and keep outputs attached to the thread.",
  },
  {
    icon: PanelsTopLeftIcon,
    title: "Artifact Builder",
    description:
      "Move from prompt to page, report, deck, or prototype without leaving the runtime.",
  },
  {
    icon: NetworkIcon,
    title: "Subagent Routing",
    description:
      "Split work across focused subagents while the lead agent keeps the final thread coherent.",
  },
  {
    icon: FileCheck2Icon,
    title: "Review Loops",
    description:
      "Inspect intermediate files, preserve context, and continue work from durable state.",
  },
  {
    icon: WorkflowIcon,
    title: "Custom Harnesses",
    description:
      "Compose models, tools, memory, skills, policies, and sandboxes for your own agent system.",
  },
];

export function CaseStudySection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("bg-[#07090b] px-4", className)}
      title="Harness Blueprints"
      subtitle={`${APP_BRAND_NAME} is designed around reusable execution patterns, not a single demo workflow.`}
    >
      <div className="container-md mx-auto mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {blueprints.map((blueprint) => {
          const Icon = blueprint.icon;
          return (
            <article
              key={blueprint.title}
              className="group relative min-h-56 overflow-hidden rounded-md border border-white/10 bg-white/[0.035] p-5 transition-colors hover:border-cyan-200/35 hover:bg-white/[0.055]"
            >
              <div className="flex size-10 items-center justify-center rounded-sm bg-cyan-200/10 text-cyan-100">
                <Icon className="size-5" />
              </div>
              <h3 className="mt-8 text-xl font-semibold text-white">
                {blueprint.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-white/60">
                {blueprint.description}
              </p>
              <div className="absolute inset-x-5 bottom-0 h-px bg-linear-to-r from-cyan-200/0 via-cyan-200/45 to-cyan-200/0 opacity-0 transition-opacity group-hover:opacity-100" />
            </article>
          );
        })}
      </div>
    </Section>
  );
}

"use client";

import {
  BadgeCheckIcon,
  BracesIcon,
  BoxesIcon,
  GitMergeIcon,
  ShieldCheckIcon,
  WorkflowIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { Section } from "../section";

const routingSteps = [
  {
    icon: WorkflowIcon,
    label: "intent",
    value: "release-readiness",
    description: "The lead agent classifies the work before selecting tools.",
  },
  {
    icon: BoxesIcon,
    label: "skill",
    value: "public:artifact-builder",
    description: "Execution uses a category-qualified skill ID.",
  },
  {
    icon: ShieldCheckIcon,
    label: "policy",
    value: "custom:policy-review",
    description: "Sensitive actions pass through a configured review lane.",
  },
  {
    icon: BracesIcon,
    label: "tool",
    value: "workspace:manifest-writer",
    description: "Generated outputs stay attached to the active thread.",
  },
  {
    icon: GitMergeIcon,
    label: "handoff",
    value: "team:release-packager",
    description: "Subagent results return to one durable run state.",
  },
  {
    icon: BadgeCheckIcon,
    label: "evidence",
    value: "run.metadata.trace",
    description: "The harness records what ran, where, and why.",
  },
];

export function SkillsSection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("w-full bg-[#0b0d10]", className)}
      title="Skill Routing Without Name Collisions"
      subtitle="VassilFlow treats skills as stable capabilities. Display names can be friendly; execution stays bound to explicit IDs, policies, and run metadata."
    >
      <div className="container-md mx-auto mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {routingSteps.map((step) => {
          const Icon = step.icon;
          return (
            <article
              key={step.value}
              className="border border-white/10 bg-white/[0.035] p-5"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-sm bg-emerald-200/10 text-emerald-100">
                  <Icon className="size-5" />
                </div>
                <span className="font-mono text-xs text-white/44">
                  {step.label}
                </span>
              </div>
              <h3 className="mt-7 font-mono text-base break-words text-white">
                {step.value}
              </h3>
              <p className="mt-3 text-sm leading-7 text-white/60">
                {step.description}
              </p>
            </article>
          );
        })}
      </div>
    </Section>
  );
}

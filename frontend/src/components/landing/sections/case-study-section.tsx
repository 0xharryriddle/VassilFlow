import {
  ArrowRightIcon,
  BoxesIcon,
  FileCheck2Icon,
  GitBranchIcon,
  RouteIcon,
} from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import { Section } from "../section";

const demoThreads = [
  {
    icon: GitBranchIcon,
    title: "Superagent Orchestrator",
    href: "/workspace/chats/vf-demo-orchestrator-run",
    description:
      "A lead agent plans a multi-lane run, delegates work, and ships a runbook artifact.",
    meta: "lead + subagents",
  },
  {
    icon: RouteIcon,
    title: "Skill Routing",
    href: "/workspace/chats/vf-demo-skill-routing",
    description:
      "Stable skill IDs route execution while display aliases stay flexible.",
    meta: "skills + policy",
  },
  {
    icon: BoxesIcon,
    title: "Artifact Package",
    href: "/workspace/chats/vf-demo-artifact-builder",
    description:
      "Workspace outputs become a deployable review package with a manifest.",
    meta: "files + outputs",
  },
  {
    icon: FileCheck2Icon,
    title: "Runtime Readiness",
    href: "/workspace/chats/vf-demo-runtime-readiness",
    description:
      "Readiness checks cover config, sandbox boundaries, frontend health, and demo integrity.",
    meta: "checks + handoff",
  },
];

export function CaseStudySection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("bg-[#07090b]", className)}
      title="VassilFlow Demo Threads"
      subtitle="Open the workspace with fixtures that show the harness operating through plans, skills, files, checks, and deliverables."
    >
      <div className="container-md mx-auto mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {demoThreads.map((thread) => {
          const Icon = thread.icon;
          return (
            <Link
              key={thread.title}
              href={thread.href}
              className="group flex min-h-64 flex-col border border-white/10 bg-white/[0.035] p-5 transition-colors hover:border-cyan-200/35 hover:bg-white/[0.055]"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex size-10 items-center justify-center rounded-sm bg-cyan-200/10 text-cyan-100">
                  <Icon className="size-5" />
                </div>
                <ArrowRightIcon className="size-4 text-white/36 transition-transform group-hover:translate-x-1 group-hover:text-cyan-100" />
              </div>
              <p className="mt-8 font-mono text-xs text-cyan-100/70">
                {thread.meta}
              </p>
              <h3 className="mt-3 text-xl font-semibold text-white">
                {thread.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-white/60">
                {thread.description}
              </p>
            </Link>
          );
        })}
      </div>
    </Section>
  );
}

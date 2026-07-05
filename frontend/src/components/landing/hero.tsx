"use client";

import {
  ArrowRightIcon,
  BracesIcon,
  CheckCircle2Icon,
  CircleDotIcon,
  FileTextIcon,
  GitBranchIcon,
  PlayIcon,
  RouteIcon,
  ShieldCheckIcon,
  WorkflowIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  APP_BRAND_DESCRIPTION,
  APP_BRAND_NAME,
  APP_REPOSITORY_URL,
} from "@/core/brand";
import { cn } from "@/lib/utils";

const runLanes = [
  {
    icon: GitBranchIcon,
    label: "Lead",
    detail: "Plans the run and keeps the final thread coherent.",
    tone: "text-cyan-100 bg-cyan-300/12 border-cyan-200/20",
  },
  {
    icon: RouteIcon,
    label: "Research",
    detail: "Collects sources, facts, and competing signals.",
    tone: "text-emerald-100 bg-emerald-300/12 border-emerald-200/20",
  },
  {
    icon: FileTextIcon,
    label: "Builder",
    detail: "Turns findings into artifacts inside the workspace.",
    tone: "text-amber-100 bg-amber-300/12 border-amber-200/20",
  },
  {
    icon: ShieldCheckIcon,
    label: "Reviewer",
    detail: "Checks boundaries, tests, and readiness before delivery.",
    tone: "text-rose-100 bg-rose-300/12 border-rose-200/20",
  },
];

const timeline = [
  ["00:00", "plan", "Break objective into verifiable work packets"],
  ["00:11", "delegate", "Assign skill and subagent lanes"],
  ["00:29", "execute", "Mount workspace, run tools, write artifacts"],
  ["01:04", "review", "Verify output, preserve state, summarize handoff"],
];

const signals = [
  "VASSILFLOW_HOME",
  "public:research",
  "custom:review",
  "sandbox:ready",
  "memory:scoped",
  "artifacts:synced",
];

export function Hero({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "relative isolate flex min-h-[88svh] w-full overflow-hidden bg-[#06080a] lg:min-h-[92svh]",
        className,
      )}
    >
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.055)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] [background-size:48px_48px]" />
      <div className="absolute inset-0 bg-[linear-gradient(120deg,rgba(6,8,10,0.2),rgba(6,8,10,0.92)_44%,#06080a_78%)]" />

      <div className="container-md relative z-10 mx-auto grid min-h-[88svh] w-full grid-cols-1 gap-8 px-4 pt-22 pb-10 lg:min-h-[92svh] lg:grid-cols-[minmax(0,0.92fr)_minmax(520px,1.08fr)] lg:items-center lg:gap-10 lg:pt-24 lg:pb-14">
        <div className="max-w-3xl pt-8 lg:pt-0">
          <div className="mb-5 inline-flex items-center gap-2 rounded-sm border border-cyan-200/20 bg-cyan-200/8 px-3 py-2 text-sm font-medium text-cyan-100">
            <WorkflowIcon className="size-4" />
            Independent SuperAgent Harness
          </div>

          <h1 className="text-5xl font-semibold text-white md:text-7xl">
            {APP_BRAND_NAME}
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-8 text-white/72 md:text-xl">
            {APP_BRAND_DESCRIPTION} Coordinate skills, subagents, memory, tools,
            and sandboxed execution through a VassilFlow-native runtime.
          </p>

          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button size="lg" asChild className="h-12 rounded-md px-5">
              <Link href="/workspace">
                Get Started
                <ArrowRightIcon className="size-4" />
              </Link>
            </Button>
            <Button
              size="lg"
              variant="outline"
              asChild
              className="h-12 rounded-md border-white/15 bg-white/5 px-5 text-white hover:bg-white/10"
            >
              <Link href="/workspace/chats/vf-demo-orchestrator-run">
                Open Demo
                <PlayIcon className="size-4" />
              </Link>
            </Button>
            <Button
              size="lg"
              variant="ghost"
              asChild
              className="hidden h-12 rounded-md px-5 text-white/80 hover:bg-white/10 hover:text-white sm:inline-flex"
            >
              <Link
                href={APP_REPOSITORY_URL}
                target="_blank"
                rel="noopener noreferrer"
              >
                Source
                <BracesIcon className="size-4" />
              </Link>
            </Button>
          </div>

          <div className="mt-8 hidden max-w-2xl grid-cols-2 gap-2 text-xs font-medium text-white/62 sm:grid sm:grid-cols-3">
            {signals.map((signal) => (
              <span
                key={signal}
                className="min-w-0 rounded-sm border border-white/10 bg-white/[0.045] px-3 py-2 font-mono"
              >
                {signal}
              </span>
            ))}
          </div>

          <div className="mt-7 hidden border border-white/10 bg-black/38 p-4 sm:block lg:hidden">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-medium text-white/82">
                <CircleDotIcon className="size-4 text-emerald-300" />
                Harness Run
              </div>
              <span className="font-mono text-xs text-emerald-200">ready</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {runLanes.slice(0, 4).map((lane) => {
                const Icon = lane.icon;
                return (
                  <div
                    key={lane.label}
                    className="border border-white/10 bg-white/[0.035] p-3"
                  >
                    <Icon className="mb-3 size-4 text-cyan-100" />
                    <div className="text-sm font-semibold text-white">
                      {lane.label}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="relative hidden min-h-[560px] w-full overflow-hidden border border-white/10 bg-black/38 shadow-2xl shadow-black/50 backdrop-blur-sm lg:block">
          <div className="flex h-12 items-center justify-between border-b border-white/10 bg-white/[0.04] px-4">
            <div className="flex items-center gap-2 text-sm font-medium text-white/82">
              <CircleDotIcon className="size-4 text-emerald-300" />
              Live Harness Run
            </div>
            <div className="font-mono text-xs text-white/46">
              vf-demo-orchestrator-run
            </div>
          </div>

          <div className="grid gap-4 p-4 lg:grid-cols-[1fr_0.92fr]">
            <div className="space-y-3">
              {runLanes.map((lane, index) => {
                const Icon = lane.icon;
                return (
                  <div
                    key={lane.label}
                    className="border border-white/10 bg-white/[0.035] p-4"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={cn(
                          "flex size-9 items-center justify-center rounded-sm border",
                          lane.tone,
                        )}
                      >
                        <Icon className="size-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-white">
                          {lane.label}
                        </div>
                        <div className="font-mono text-xs text-white/42">
                          lane.{index + 1}
                        </div>
                      </div>
                      <CheckCircle2Icon className="ml-auto size-4 text-emerald-300" />
                    </div>
                    <p className="mt-3 text-sm leading-6 text-white/58">
                      {lane.detail}
                    </p>
                  </div>
                );
              })}
            </div>

            <div className="flex flex-col border border-white/10 bg-[#080a0c]/88">
              <div className="border-b border-white/10 px-4 py-3 font-mono text-xs text-white/48">
                run.log
              </div>
              <div className="space-y-4 p-4">
                {timeline.map(([time, phase, detail]) => (
                  <div key={phase} className="grid grid-cols-[48px_1fr] gap-3">
                    <div className="font-mono text-xs text-cyan-200/75">
                      {time}
                    </div>
                    <div>
                      <div className="font-mono text-xs text-white">
                        {phase}
                      </div>
                      <p className="mt-1 text-sm leading-6 text-white/55">
                        {detail}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-auto border-t border-white/10 p-4">
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="font-mono text-white/48">
                    readiness score
                  </span>
                  <span className="font-mono text-emerald-200">97%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-sm bg-white/10">
                  <div className="h-full w-[97%] bg-emerald-300" />
                </div>
              </div>
            </div>
          </div>

          <div className="absolute right-0 bottom-0 left-0 border-t border-white/10 bg-white/[0.035] px-4 py-3">
            <div className="flex flex-wrap gap-2 text-xs text-white/54">
              <span className="font-mono text-cyan-100">artifact:</span>
              <span>/mnt/user-data/outputs/orchestrator-runbook.md</span>
              <span className="font-mono text-emerald-100">status: ready</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

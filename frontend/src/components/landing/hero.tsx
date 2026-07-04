"use client";

import {
  ArrowRightIcon,
  BoxesIcon,
  BracesIcon,
  CheckCircle2Icon,
  CpuIcon,
  GitBranchIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  APP_BRAND_DESCRIPTION,
  APP_BRAND_NAME,
  APP_REPOSITORY_URL,
} from "@/core/brand";
import { cn } from "@/lib/utils";

const workflow = [
  {
    icon: GitBranchIcon,
    label: "Plan",
    detail: "Break long work into traceable steps",
  },
  {
    icon: BoxesIcon,
    label: "Delegate",
    detail: "Route work to skills, tools, and subagents",
  },
  {
    icon: ShieldCheckIcon,
    label: "Run",
    detail: "Execute in an isolated workspace",
  },
  {
    icon: CheckCircle2Icon,
    label: "Deliver",
    detail: "Return files, reports, apps, and decisions",
  },
];

const signals = [
  "VASSILFLOW_HOME",
  "skills/public:research",
  "sandbox:ready",
  "memory:scoped",
];

export function Hero({ className }: { className?: string }) {
  return (
    <section
      className={cn(
        "relative isolate flex min-h-[92svh] w-full overflow-hidden bg-[#07090b]",
        className,
      )}
    >
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.06)_1px,transparent_1px)] [background-size:56px_56px] opacity-28" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(42,166,166,0.22),transparent_52%),linear-gradient(180deg,rgba(7,9,11,0.35),#07090b_86%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-20 h-px bg-linear-to-r from-transparent via-cyan-300/40 to-transparent" />

      <div className="absolute inset-x-4 bottom-8 hidden h-44 grid-cols-4 gap-3 opacity-75 md:grid lg:inset-x-12">
        {workflow.map((item, index) => {
          const Icon = item.icon;
          return (
            <div
              key={item.label}
              className="relative overflow-hidden rounded-md border border-white/10 bg-black/35 p-4 backdrop-blur-sm"
            >
              <div className="absolute inset-x-0 top-0 h-1 bg-linear-to-r from-cyan-300 via-emerald-300 to-amber-300 opacity-80" />
              <div className="flex items-center gap-3 text-white">
                <Icon className="size-5 text-cyan-200" />
                <span className="font-medium">{item.label}</span>
                <span className="ml-auto font-mono text-xs text-white/35">
                  0{index + 1}
                </span>
              </div>
              <p className="mt-4 text-sm leading-6 text-white/58">
                {item.detail}
              </p>
            </div>
          );
        })}
      </div>

      <div className="container-md relative z-10 mx-auto flex min-h-[92svh] flex-col items-center justify-center px-4 pt-28 pb-28 text-center">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-200/20 bg-cyan-200/8 px-4 py-2 text-sm font-medium text-cyan-100">
          <CpuIcon className="size-4" />
          Independent SuperAgent Harness
        </div>

        <h1 className="text-6xl font-semibold tracking-tight text-white md:text-8xl">
          {APP_BRAND_NAME}
        </h1>

        <p className="mt-6 max-w-3xl text-xl leading-9 text-balance text-white/72 md:text-2xl">
          {APP_BRAND_DESCRIPTION} Run long-horizon work with skills, memory,
          subagents, tools, and sandboxed execution under one VassilFlow-native
          runtime.
        </p>

        <div className="mt-9 flex flex-col items-center gap-3 sm:flex-row">
          <Button size="lg" asChild className="h-12 rounded-md px-5">
            <Link href="/workspace">
              Open Workspace
              <ArrowRightIcon className="size-4" />
            </Link>
          </Button>
          <Button
            size="lg"
            variant="outline"
            asChild
            className="h-12 rounded-md border-white/15 bg-white/5 px-5 text-white hover:bg-white/10"
          >
            <Link
              href={APP_REPOSITORY_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              View Source
              <BracesIcon className="size-4" />
            </Link>
          </Button>
        </div>

        <div className="mt-10 flex max-w-3xl flex-wrap justify-center gap-2 text-xs font-medium text-white/60">
          {signals.map((signal) => (
            <span
              key={signal}
              className="rounded-sm border border-white/10 bg-white/5 px-3 py-2 font-mono"
            >
              {signal}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

"use client";

import {
  AnimatedSpan,
  Terminal,
  TypingAnimation,
} from "@/components/ui/terminal";
import { APP_BRAND_NAME } from "@/core/brand";

import { Section } from "../section";

const runtimeTags = [
  "Filesystem",
  "Shell",
  "Browser",
  "MCP",
  "Artifacts",
  "Policies",
];

export function SandboxSection({ className }: { className?: string }) {
  return (
    <Section
      className={className}
      title="Isolated Execution Layer"
      subtitle={
        <p>
          {APP_BRAND_NAME} gives agents a bounded workspace for real file work,
          command execution, tool calls, and artifact generation.
        </p>
      }
    >
      <div className="container-md mx-auto mt-10 flex w-full flex-col items-stretch gap-10 px-4 lg:flex-row">
        <div className="w-full flex-1">
          <Terminal className="h-[360px] w-full rounded-md border-white/10 bg-black/45">
            <TypingAnimation>$ vassilflow run evidence-brief</TypingAnimation>
            <AnimatedSpan delay={800} className="text-zinc-400">
              loading config from VASSILFLOW_CONFIG_PATH
            </AnimatedSpan>

            <TypingAnimation delay={1300}>
              $ mount workspace /mnt/user-data
            </TypingAnimation>
            <AnimatedSpan delay={2000} className="text-green-500">
              ok workspace mounted
            </AnimatedSpan>

            <TypingAnimation delay={2500}>
              $ python tools/analyze_sources.py
            </TypingAnimation>
            <AnimatedSpan delay={3300} className="text-cyan-400">
              ok extracted 42 source notes
            </AnimatedSpan>

            <TypingAnimation delay={3800}>
              $ write outputs/evidence-brief.md
            </TypingAnimation>
            <AnimatedSpan delay={4500} className="text-green-500">
              ok artifact written
            </AnimatedSpan>

            <TypingAnimation delay={5000}>
              $ package outputs --manifest
            </TypingAnimation>
            <AnimatedSpan delay={5700} className="text-amber-300">
              ready for review
            </AnimatedSpan>
          </Terminal>
        </div>

        <div className="flex w-full flex-1 flex-col justify-center">
          <p className="text-sm font-medium tracking-[0.24em] text-cyan-200 uppercase">
            Runtime Boundary
          </p>
          <h2 className="mt-4 max-w-xl text-4xl font-semibold tracking-tight text-white lg:text-5xl">
            Work happens inside a controlled VassilFlow workspace.
          </h2>
          <p className="mt-5 max-w-xl text-lg leading-8 text-white/60">
            The sandbox layer keeps long tasks practical: agents can inspect
            uploads, create files, run scripts, and preserve outputs while the
            harness controls paths, policies, and runtime state.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            {runtimeTags.map((tag) => (
              <span
                key={tag}
                className="rounded-sm border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-white/70"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}

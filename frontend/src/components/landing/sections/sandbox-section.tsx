"use client";

import { Terminal } from "@/components/ui/terminal";
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
          <Terminal
            sequence={false}
            className="h-[360px] w-full rounded-md border-white/10 bg-black/45"
          >
            <span className="text-zinc-100">
              $ vassilflow run release-readiness
            </span>
            <span className="text-zinc-400">
              run_id=vf-run-2049 policy=team/default
            </span>

            <span className="text-zinc-100">
              $ mount workspace /mnt/user-data
            </span>
            <span className="text-green-500">ok workspace mounted</span>

            <span className="text-zinc-100">
              $ check sandbox boundary --tools filesystem,shell,mcp
            </span>
            <span className="text-cyan-400">ok policy gate passed</span>

            <span className="text-zinc-100">
              $ write outputs/orchestrator-runbook.md
            </span>
            <span className="text-green-500">ok artifact written</span>

            <span className="text-zinc-100">$ package outputs --manifest</span>
            <span className="text-amber-300">ready for review</span>
          </Terminal>
        </div>

        <div className="flex w-full flex-1 flex-col justify-center">
          <p className="text-sm font-medium text-cyan-200 uppercase">
            Runtime Boundary
          </p>
          <h2 className="mt-4 max-w-xl text-4xl font-semibold text-white lg:text-5xl">
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

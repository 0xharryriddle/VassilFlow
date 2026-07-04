"use client";

import { APP_BRAND_NAME } from "@/core/brand";
import { cn } from "@/lib/utils";

import ProgressiveSkillsAnimation from "../progressive-skills-animation";
import { Section } from "../section";

export function SkillsSection({ className }: { className?: string }) {
  return (
    <Section
      className={cn("min-h-[calc(100vh-64px)] w-full bg-[#0b0d10]", className)}
      title="Skill Runtime"
      subtitle={
        <div>
          Skills are loaded by stable VassilFlow identities such as{" "}
          <span className="font-mono text-cyan-100">public:research</span> and{" "}
          <span className="font-mono text-cyan-100">custom:review</span>.
          <br />
          Extend {APP_BRAND_NAME} with focused skill folders without coupling
          the runtime to one legacy workflow.
        </div>
      }
    >
      <div className="relative overflow-hidden">
        <ProgressiveSkillsAnimation />
      </div>
    </Section>
  );
}

"use client";

import { ArrowRightIcon, BracesIcon, PlayIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { APP_BRAND_NAME, APP_REPOSITORY_URL } from "@/core/brand";

import { Section } from "../section";

export function CommunitySection() {
  return (
    <Section
      className="bg-[#0b0d10]"
      title="Start From a Working Harness"
      subtitle={`${APP_BRAND_NAME} is ready to be extended into domain-specific superagent systems with real files, policies, skills, and review loops.`}
    >
      <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Button className="h-12 rounded-md px-5 text-base" size="lg" asChild>
          <Link href="/workspace">
            Open Workspace
            <ArrowRightIcon className="size-4" />
          </Link>
        </Button>
        <Button
          className="h-12 rounded-md px-5 text-base"
          size="lg"
          variant="outline"
          asChild
        >
          <Link href="/workspace/chats/vf-demo-orchestrator-run">
            View Demo
            <PlayIcon className="size-4" />
          </Link>
        </Button>
        <Button
          className="h-12 rounded-md px-5 text-base"
          size="lg"
          variant="ghost"
          asChild
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
    </Section>
  );
}

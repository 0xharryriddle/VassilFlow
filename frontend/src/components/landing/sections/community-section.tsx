"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { APP_BRAND_NAME, APP_REPOSITORY_URL } from "@/core/brand";

import { Section } from "../section";

export function CommunitySection() {
  return (
    <Section
      className="bg-[#0b0d10] px-4"
      title="Build the Harness With Us"
      subtitle={`${APP_BRAND_NAME} is open for engineers who want agent systems that can actually operate across files, tools, memory, and execution environments.`}
    >
      <div className="mt-10 flex justify-center">
        <Button className="h-12 rounded-md px-5 text-base" size="lg" asChild>
          <Link
            href={APP_REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            <GitHubLogoIcon />
            Contribute on GitHub
            <ArrowRightIcon className="size-4" />
          </Link>
        </Button>
      </div>
    </Section>
  );
}

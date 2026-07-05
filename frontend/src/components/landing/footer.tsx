import Link from "next/link";

import { APP_BRAND_NAME, APP_REPOSITORY_URL } from "@/core/brand";
import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
};

export function Footer({ className }: FooterProps) {
  const year = new Date().getFullYear();

  return (
    <footer
      className={cn(
        "mx-auto flex w-full flex-col border-t border-white/10 bg-[#06080a]",
        className,
      )}
    >
      <div className="container-md mx-auto grid gap-8 px-4 py-10 md:grid-cols-[1fr_auto] md:items-end">
        <div>
          <p className="text-lg font-semibold text-white">{APP_BRAND_NAME}</p>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-white/58">
            Open-source superagent harness for traceable long-horizon runs,
            policy-aware tools, durable memory, and workspace artifacts.
          </p>
        </div>
        <div className="flex flex-wrap gap-4 text-sm text-white/62">
          <Link href="/workspace" className="hover:text-white">
            Workspace
          </Link>
          <Link
            href="/workspace/chats/vf-demo-orchestrator-run"
            className="hover:text-white"
          >
            Demo
          </Link>
          <a
            href={APP_REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white"
          >
            Source
          </a>
        </div>
      </div>
      <div className="border-t border-white/8 px-4 py-5 text-center text-xs text-white/42">
        MIT License · © {year} {APP_BRAND_NAME}
      </div>
    </footer>
  );
}

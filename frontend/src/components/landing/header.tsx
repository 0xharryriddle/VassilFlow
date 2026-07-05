import Image from "next/image";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { APP_BRAND_NAME, APP_REPOSITORY_URL } from "@/core/brand";
import type { Locale } from "@/core/i18n/locale";
import { getI18n } from "@/core/i18n/server";
import { cn } from "@/lib/utils";

export type HeaderProps = {
  className?: string;
  homeURL?: string;
  locale?: Locale;
};

export async function Header({ className, homeURL, locale }: HeaderProps) {
  const resolvedHomeURL = homeURL ?? "/";
  const isExternalHome = resolvedHomeURL.startsWith("http");
  const { locale: resolvedLocale, t } = await getI18n(locale);
  const lang = resolvedLocale.substring(0, 2);

  return (
    <header
      className={cn(
        "container-md fixed top-0 right-0 left-0 z-20 mx-auto flex h-16 items-center justify-between border-b border-white/8 bg-[#080a0c]/88 px-4 backdrop-blur-md",
        className,
      )}
    >
      <a
        href={resolvedHomeURL}
        target={isExternalHome ? "_blank" : "_self"}
        rel={isExternalHome ? "noopener noreferrer" : undefined}
        className="flex min-w-0 items-center gap-3"
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-sm border border-white/12 bg-white">
          <Image
            src="/images/vassilflow-mark.svg"
            width={26}
            height={26}
            alt=""
            priority
          />
        </span>
        <h1 className="truncate text-lg font-semibold text-white">
          {APP_BRAND_NAME}
        </h1>
      </a>

      <nav className="ml-auto hidden items-center gap-6 text-sm font-medium md:flex">
        <Link
          href="/workspace"
          className="text-white/68 transition-colors hover:text-white"
        >
          Workspace
        </Link>
        <Link
          href="/workspace/chats/vf-demo-orchestrator-run"
          className="text-white/68 transition-colors hover:text-white"
        >
          Demo
        </Link>
        <Link
          href={`/${lang}/docs`}
          className="text-white/68 transition-colors hover:text-white"
        >
          {t.home.docs}
        </Link>
        <Link
          href="/blog/posts"
          className="text-white/68 transition-colors hover:text-white"
        >
          {t.home.blog}
        </Link>
      </nav>

      <div className="ml-4 flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          asChild
          className="hidden rounded-md border-white/14 bg-white/5 text-white hover:bg-white/10 sm:inline-flex"
        >
          <a
            href={APP_REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            Source
          </a>
        </Button>
        <Button size="sm" asChild className="rounded-md">
          <Link href="/workspace">Open</Link>
        </Button>
      </div>

      <hr className="absolute top-16 right-0 left-0 z-10 m-0 h-px w-full border-none bg-white/10" />
    </header>
  );
}

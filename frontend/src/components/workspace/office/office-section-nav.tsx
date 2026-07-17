"use client";

import { Clock3Icon, LayoutTemplateIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function OfficeSectionNav() {
  const pathname = usePathname();
  const { t } = useI18n();
  const templatesActive = pathname.startsWith("/workspace/office/templates");
  const items = [
    {
      href: "/workspace/office",
      label: t.office.recent,
      icon: Clock3Icon,
      active: !templatesActive,
    },
    {
      href: "/workspace/office/templates",
      label: t.office.templates,
      icon: LayoutTemplateIcon,
      active: templatesActive,
    },
  ];

  return (
    <nav
      aria-label={t.office.title}
      className="flex h-11 shrink-0 items-end gap-5 border-b px-4 sm:px-6"
    >
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={item.active ? "page" : undefined}
          className={cn(
            "text-muted-foreground hover:text-foreground focus-visible:ring-ring relative flex h-10 items-center gap-1.5 px-0.5 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none",
            item.active && "text-foreground after:bg-foreground",
            "after:absolute after:inset-x-0 after:bottom-0 after:h-0.5",
          )}
        >
          <item.icon className="size-4" />
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

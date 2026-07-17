"use client";

import {
  CheckCircle2Icon,
  Clock3Icon,
  LayoutTemplateIcon,
  SearchIcon,
  ShieldAlertIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/core/i18n/hooks";
import { type OfficeTemplateSummary, useOfficeTemplates } from "@/core/office";
import { formatTimeAgo } from "@/core/utils/datetime";

import { OfficePreviewImage } from "./office-preview-image";
import { OfficeSectionNav } from "./office-section-nav";

function TemplateCard({ template }: { template: OfficeTemplateSummary }) {
  const { locale, t } = useI18n();
  const version = template.active_version;
  const preview = version.render.preview_pages[0];
  const reviewed = version.render.visual_review_status === "reviewed";
  const ReviewIcon = reviewed ? CheckCircle2Icon : Clock3Icon;

  return (
    <Link
      href={`/workspace/office/templates/${template.template_id}`}
      className="group bg-background hover:border-foreground/25 hover:bg-muted/20 focus-visible:ring-ring overflow-hidden rounded-md border transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <div className="bg-muted/45 relative aspect-[16/10] overflow-hidden border-b">
        {preview ? (
          <OfficePreviewImage
            preview={preview}
            alt={t.office.previewAlt(template.title, preview.page)}
            className="size-full bg-white p-3 transition-transform duration-200 group-hover:scale-[1.015] dark:bg-neutral-100"
          />
        ) : (
          <div className="flex size-full items-center justify-center">
            <LayoutTemplateIcon className="text-muted-foreground size-12" />
          </div>
        )}
        <Badge
          variant={template.status === "published" ? "default" : "secondary"}
          className="absolute top-2 left-2 rounded-md"
        >
          {template.status === "published"
            ? t.office.published
            : t.office.draft}
        </Badge>
      </div>
      <div className="space-y-3 p-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium" title={template.title}>
            {template.title}
          </h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {t.office.version(version.version)} /{" "}
            {formatTimeAgo(template.updated_at, locale)}
          </p>
        </div>
        <div className="text-muted-foreground flex items-center justify-between gap-2 border-t pt-2.5 text-xs">
          <span className="flex min-w-0 items-center gap-1.5 truncate">
            <ReviewIcon className="size-3.5 shrink-0" />
            <span className="truncate">
              {reviewed ? t.office.reviewed : t.office.reviewPending}
            </span>
          </span>
          <span className="shrink-0">
            {t.office.slots(version.slot_count)} /{" "}
            {t.office.slides(version.slide_count)}
          </span>
        </div>
      </div>
    </Link>
  );
}

function TemplatesSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className="overflow-hidden rounded-md border">
          <Skeleton className="aspect-[16/10] w-full rounded-none" />
          <div className="space-y-3 p-3">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function OfficeTemplates() {
  const { t } = useI18n();
  const templatesQuery = useOfficeTemplates();
  const [query, setQuery] = useState("");
  const templates = useMemo(
    () => templatesQuery.data?.templates ?? [],
    [templatesQuery.data?.templates],
  );
  const filteredTemplates = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return templates.filter(
      (template) =>
        !normalized || template.title.toLocaleLowerCase().includes(normalized),
    );
  }, [query, templates]);

  return (
    <div className="flex size-full min-w-0 flex-col">
      <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <SidebarTrigger className="md:hidden" />
          <h1 className="truncate text-xl font-semibold">{t.office.title}</h1>
        </div>
        <Button asChild>
          <Link href="/workspace/office/templates/new">
            <UploadIcon />
            {t.office.importTemplate}
          </Link>
        </Button>
      </header>

      <OfficeSectionNav />

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto w-full max-w-7xl space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-medium">{t.office.templates}</h2>
              {!templatesQuery.isLoading && (
                <p className="text-muted-foreground mt-0.5 text-sm">
                  {t.office.templateCount(filteredTemplates.length)}
                </p>
              )}
            </div>
            <div className="relative min-w-0 sm:w-72">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t.office.searchTemplates}
                aria-label={t.office.searchTemplates}
                className="pl-9"
              />
            </div>
          </div>

          {templatesQuery.isLoading ? (
            <TemplatesSkeleton />
          ) : templatesQuery.isError ? (
            <Empty className="min-h-72 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ShieldAlertIcon />
                </EmptyMedia>
                <EmptyTitle>{t.office.templateLoadError}</EmptyTitle>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  variant="outline"
                  onClick={() => void templatesQuery.refetch()}
                >
                  {t.office.retry}
                </Button>
              </EmptyContent>
            </Empty>
          ) : templates.length === 0 ? (
            <Empty className="min-h-72 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <LayoutTemplateIcon />
                </EmptyMedia>
                <EmptyTitle>{t.office.noTemplatesTitle}</EmptyTitle>
                <EmptyDescription>
                  {t.office.noTemplatesDescription}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button asChild>
                  <Link href="/workspace/office/templates/new">
                    <UploadIcon />
                    {t.office.importTemplate}
                  </Link>
                </Button>
              </EmptyContent>
            </Empty>
          ) : filteredTemplates.length === 0 ? (
            <Empty className="min-h-72 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SearchIcon />
                </EmptyMedia>
                <EmptyTitle>{t.office.noMatchesTitle}</EmptyTitle>
                <EmptyDescription>
                  {t.office.noMatchesDescription}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button variant="outline" onClick={() => setQuery("")}>
                  <XIcon />
                  {t.office.clearFilters}
                </Button>
              </EmptyContent>
            </Empty>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {filteredTemplates.map((template) => (
                <TemplateCard key={template.template_id} template={template} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

"use client";

import {
  CheckCircle2Icon,
  Clock3Icon,
  FilesIcon,
  LayoutTemplateIcon,
  SearchIcon,
  ShieldAlertIcon,
  SparklesIcon,
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import {
  type OfficeFormat,
  type OfficeProjectSummary,
  useOfficeProjects,
} from "@/core/office";
import { formatTimeAgo } from "@/core/utils/datetime";

import { OfficeFormatIcon } from "./office-format-icon";
import { OfficeNewMenu } from "./office-new-menu";
import { OfficePreviewImage } from "./office-preview-image";
import { OfficeSectionNav } from "./office-section-nav";

type FormatFilter = "all" | OfficeFormat;

function reviewLabel(status: string, t: ReturnType<typeof useI18n>["t"]) {
  switch (status) {
    case "pending":
      return t.office.reviewPending;
    case "reviewed":
      return t.office.reviewed;
    case "approved":
      return t.office.approved;
    case "changes_requested":
      return t.office.changesRequested;
    case "external_review_required":
      return t.office.externalReviewRequired;
    case "not_performed":
      return t.office.notPerformed;
    default:
      return t.office.unknownStatus;
  }
}

function ProjectCard({ project }: { project: OfficeProjectSummary }) {
  const { locale, t } = useI18n();
  const render = project.current_revision.latest_render;
  const preview = render?.preview_pages[0];
  const reviewStatus = project.current_revision.quality.visual_review_status;
  const ReviewIcon =
    reviewStatus === "reviewed" || reviewStatus === "approved"
      ? CheckCircle2Icon
      : reviewStatus === "external_review_required" ||
          reviewStatus === "changes_requested"
        ? ShieldAlertIcon
        : Clock3Icon;

  return (
    <Link
      href={`/workspace/office/projects/${project.project_id}`}
      className="group bg-background hover:border-foreground/25 hover:bg-muted/20 focus-visible:ring-ring overflow-hidden rounded-md border transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <div className="bg-muted/45 relative aspect-[16/10] overflow-hidden border-b">
        {preview ? (
          <OfficePreviewImage
            preview={preview}
            alt={t.office.previewAlt(project.title, preview.page)}
            className="size-full bg-white p-3 transition-transform duration-200 group-hover:scale-[1.015] dark:bg-neutral-100"
          />
        ) : (
          <div className="flex size-full items-center justify-center">
            <OfficeFormatIcon format={project.format} className="size-12" />
          </div>
        )}
        <Badge
          variant="secondary"
          className="bg-background/92 absolute top-2 left-2 rounded-md uppercase shadow-xs"
        >
          {project.format}
        </Badge>
        <div className="absolute top-2 right-2 flex flex-col items-end gap-1">
          {project.current_revision.kind === "generation" && (
            <Badge
              variant="secondary"
              className="bg-background/92 rounded-md shadow-xs"
            >
              <SparklesIcon />
              {t.office.generated}
            </Badge>
          )}
          {project.template && (
            <Badge
              variant="secondary"
              className="bg-background/92 rounded-md shadow-xs"
            >
              <LayoutTemplateIcon />
              {t.office.templateVersion(project.template.version)}
            </Badge>
          )}
        </div>
      </div>
      <div className="space-y-3 p-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <OfficeFormatIcon format={project.format} />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-medium" title={project.title}>
              {project.title}
            </h2>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {formatTimeAgo(project.updated_at, locale)} ·{" "}
              {t.office.revision(project.current_revision.sequence)}
            </p>
          </div>
        </div>
        <div className="flex min-w-0 items-center justify-between gap-2 border-t pt-2.5 text-xs">
          <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 truncate">
            <ReviewIcon className="size-3.5 shrink-0" />
            <span className="truncate">{reviewLabel(reviewStatus, t)}</span>
          </span>
          <span className="text-muted-foreground font-mono text-[11px]">
            {project.current_revision.artifact.sha256.slice(0, 8)}
          </span>
        </div>
      </div>
    </Link>
  );
}

function RecentSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className="overflow-hidden rounded-md border">
          <Skeleton className="aspect-[16/10] w-full rounded-none" />
          <div className="space-y-3 p-3">
            <div className="flex gap-3">
              <Skeleton className="size-9 rounded-md" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function OfficeRecent() {
  const { t } = useI18n();
  const projectsQuery = useOfficeProjects();
  const [query, setQuery] = useState("");
  const [format, setFormat] = useState<FormatFilter>("all");
  const projects = useMemo(
    () => projectsQuery.data?.projects ?? [],
    [projectsQuery.data?.projects],
  );
  const filteredProjects = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return projects.filter(
      (project) =>
        (format === "all" || project.format === format) &&
        (!normalizedQuery ||
          project.title.toLocaleLowerCase().includes(normalizedQuery)),
    );
  }, [format, projects, query]);
  const filters: { value: FormatFilter; label: string }[] = [
    { value: "all", label: t.office.formatAll },
    { value: "pptx", label: t.office.formatPowerPoint },
    { value: "docx", label: t.office.formatWord },
    { value: "xlsx", label: t.office.formatExcel },
  ];

  return (
    <div className="flex size-full min-w-0 flex-col">
      <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2">
          <SidebarTrigger className="md:hidden" />
          <h1 className="truncate text-xl font-semibold">{t.office.title}</h1>
        </div>
        <OfficeNewMenu />
      </header>

      <OfficeSectionNav />

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto w-full max-w-7xl space-y-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-base font-medium">{t.office.recent}</h2>
              {!projectsQuery.isLoading && (
                <p className="text-muted-foreground mt-0.5 text-sm">
                  {t.office.projectCount(filteredProjects.length)}
                </p>
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative min-w-0 sm:w-64">
                <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                <Input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t.office.searchPlaceholder}
                  aria-label={t.office.searchPlaceholder}
                  className="pl-9"
                />
              </div>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={format}
                onValueChange={(value) => {
                  if (value) setFormat(value as FormatFilter);
                }}
                aria-label={t.office.formatAll}
                className="max-w-full justify-start overflow-x-auto"
              >
                {filters.map((filter) => (
                  <ToggleGroupItem key={filter.value} value={filter.value}>
                    {filter.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          </div>

          {projectsQuery.isLoading ? (
            <RecentSkeleton />
          ) : projectsQuery.isError ? (
            <Empty className="min-h-72 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ShieldAlertIcon />
                </EmptyMedia>
                <EmptyTitle>{t.office.loadError}</EmptyTitle>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  variant="outline"
                  onClick={() => void projectsQuery.refetch()}
                >
                  {t.office.retry}
                </Button>
              </EmptyContent>
            </Empty>
          ) : projects.length === 0 ? (
            <Empty className="min-h-72 border-0">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FilesIcon />
                </EmptyMedia>
                <EmptyTitle>{t.office.noProjectsTitle}</EmptyTitle>
                <EmptyDescription>
                  {t.office.noProjectsDescription}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <OfficeNewMenu />
              </EmptyContent>
            </Empty>
          ) : filteredProjects.length === 0 ? (
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
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setFormat("all");
                  }}
                >
                  <XIcon />
                  {t.office.clearFilters}
                </Button>
              </EmptyContent>
            </Empty>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {filteredProjects.map((project) => (
                <ProjectCard key={project.project_id} project={project} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

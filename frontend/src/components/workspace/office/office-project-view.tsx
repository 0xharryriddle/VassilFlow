"use client";

import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  DownloadIcon,
  ExternalLinkIcon,
  FileWarningIcon,
  LayoutTemplateIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import {
  collectOfficePreviewPages,
  officeArtifactURL,
  officePageCount,
  type OfficeRenderSet,
  type OfficeRevisionSummary,
  type OfficePptxSelectionObject,
  useOfficeProject,
  useOfficePptxSelectionSurface,
  useOfficeRevision,
  useOfficeRevisionComparison,
  useOfficeRevisions,
} from "@/core/office";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

import { OfficeFormatIcon } from "./office-format-icon";
import {
  OfficeObjectOverlay,
  OfficeObjectSelectionPanel,
} from "./office-object-selection";
import { OfficePreviewImage } from "./office-preview-image";
import { OfficeProjectActions } from "./office-project-actions";
import {
  OfficeGenerationEvidenceView,
  OfficeRevisionComparisonView,
  OfficeSemanticChangesView,
} from "./office-revision-review";

function readableBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function statusLabel(
  status: string,
  t: ReturnType<typeof useI18n>["t"],
): string {
  switch (status) {
    case "valid":
      return t.office.valid;
    case "invalid":
      return t.office.invalid;
    case "not_recorded":
      return t.office.notRecorded;
    case "recorded":
      return t.office.recorded;
    case "available":
      return t.office.available;
    case "not_available":
      return t.office.notAvailable;
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

function QualityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="max-w-[60%] text-right font-medium">{value}</dd>
    </div>
  );
}

function RevisionRow({
  revision,
  current,
  selected,
  onSelect,
}: {
  revision: OfficeRevisionSummary;
  current: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const { locale, t } = useI18n();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={t.office.viewRevision(revision.sequence)}
      aria-pressed={selected}
      className={cn(
        "focus-visible:ring-ring flex w-full items-start gap-3 border-b px-2 py-3 text-left transition-colors last:border-b-0 focus-visible:ring-2 focus-visible:outline-none",
        selected ? "bg-muted" : "hover:bg-muted/45",
      )}
    >
      <span
        className={cn(
          "mt-1.5 size-2 shrink-0 rounded-full",
          selected
            ? "bg-primary"
            : current
              ? "bg-foreground/55"
              : "bg-muted-foreground/35",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">
            {t.office.revision(revision.sequence)}
          </span>
          <span className="flex items-center gap-1">
            {revision.is_final && (
              <Badge variant="outline" className="rounded-md">
                {t.office.finalArtifact}
              </Badge>
            )}
            {current && (
              <Badge variant="secondary" className="rounded-md">
                {t.office.currentRevision}
              </Badge>
            )}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          {revision.kind === "baseline"
            ? t.office.baseline
            : revision.kind === "generation"
              ? t.office.generated
              : revision.kind === "restore"
                ? t.office.restore
                : t.office.edit}{" "}
          / {formatTimeAgo(revision.created_at, locale)}
        </p>
        <p className="text-muted-foreground mt-1 truncate font-mono text-[11px]">
          {revision.artifact.sha256.slice(0, 12)}
        </p>
      </div>
    </button>
  );
}

function ProjectLoading() {
  return (
    <div className="flex size-full flex-col">
      <div className="flex h-16 items-center gap-3 border-b px-4 sm:px-6">
        <Skeleton className="size-9 rounded-md" />
        <Skeleton className="h-5 w-56" />
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="bg-muted/30 flex min-h-[420px] items-center justify-center p-6">
          <Skeleton className="aspect-[4/3] h-[70%] max-h-[620px]" />
        </div>
        <div className="hidden space-y-4 border-l p-5 lg:block">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    </div>
  );
}

function ProjectLoadError({
  title,
  onRetry,
}: {
  title: string;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex size-full flex-col">
      <header className="flex h-16 items-center gap-2 border-b px-4 sm:px-6">
        <SidebarTrigger className="md:hidden" />
        <Button variant="ghost" asChild>
          <Link href="/workspace/office">
            <ArrowLeftIcon />
            {t.office.backToOffice}
          </Link>
        </Button>
      </header>
      <Empty className="border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileWarningIcon />
          </EmptyMedia>
          <EmptyTitle>{title}</EmptyTitle>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="outline" onClick={onRetry}>
            <RefreshCwIcon />
            {t.office.retry}
          </Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}

export function OfficeProjectView() {
  const { project_id: projectId, revision_id: routeRevisionId } = useParams<{
    project_id: string;
    revision_id?: string;
  }>();
  const router = useRouter();
  const { locale, t } = useI18n();
  const projectQuery = useOfficeProject(projectId);
  const revisionsQuery = useOfficeRevisions(projectId);
  const project = projectQuery.data;
  const currentRevisionId = project?.current_revision.revision_id;
  const isCurrentRevision =
    !routeRevisionId || routeRevisionId === currentRevisionId;
  const revisionQuery = useOfficeRevision(
    projectId,
    routeRevisionId,
    !!project && !isCurrentRevision,
  );
  const listedRevision = revisionsQuery.data?.revisions.find(
    (revision) => revision.revision_id === routeRevisionId,
  );
  const revision = isCurrentRevision
    ? project?.current_revision
    : (revisionQuery.data?.revision ?? listedRevision);
  const emptyRenderSet: OfficeRenderSet = useMemo(
    () => ({
      complete: false,
      page_count: 0,
      rendered_page_count: 0,
      evidence_ids: [],
      evidence: [],
    }),
    [],
  );
  const renderSet = isCurrentRevision
    ? (project?.render_set ?? emptyRenderSet)
    : (revisionQuery.data?.render_set ?? emptyRenderSet);
  const renderEvidence = useMemo(() => {
    if (renderSet.evidence.length > 0) return renderSet.evidence;
    if (isCurrentRevision) return project?.render_evidence ?? [];
    if (revisionQuery.data) return revisionQuery.data.render_evidence;
    return listedRevision?.latest_render ? [listedRevision.latest_render] : [];
  }, [
    isCurrentRevision,
    listedRevision?.latest_render,
    project?.render_evidence,
    renderSet.evidence,
    revisionQuery.data,
  ]);
  const pages = useMemo(
    () => collectOfficePreviewPages(renderEvidence),
    [renderEvidence],
  );
  const pageCount = officePageCount(renderEvidence);
  const [selectedPageNumber, setSelectedPageNumber] = useState<number | null>(
    null,
  );
  const [activeView, setActiveView] = useState<
    "preview" | "compare" | "changes"
  >("preview");
  const comparisonQuery = useOfficeRevisionComparison(
    projectId,
    revision?.revision_id,
    !!revision?.parent_revision_id,
  );
  const generationReceipt = isCurrentRevision
    ? project?.generation_receipt
    : revisionQuery.data?.generation_receipt;
  const generationPreflight = isCurrentRevision
    ? project?.generation_preflight
    : revisionQuery.data?.generation_preflight;

  useEffect(() => {
    setSelectedPageNumber((current) =>
      pages.some((page) => page.page === current)
        ? current
        : (pages[0]?.page ?? null),
    );
  }, [pages]);

  useEffect(() => {
    setActiveView("preview");
  }, [revision?.revision_id]);

  const selectedPage =
    pages.find((page) => page.page === selectedPageNumber) ?? pages[0];
  const selectionSlide =
    project?.format === "pptx" && selectedPage
      ? (selectedPage.source_slide ?? selectedPage.page)
      : null;
  const selectionQuery = useOfficePptxSelectionSurface(
    projectId,
    revision?.revision_id,
    selectionSlide,
    activeView === "preview" && project?.format === "pptx",
  );
  const [selectedObjectPath, setSelectedObjectPath] = useState<string | null>(
    null,
  );

  useEffect(() => {
    setSelectedObjectPath(null);
  }, [revision?.revision_id, selectionSlide]);

  const handleObjectSelect = (object: OfficePptxSelectionObject) => {
    setSelectedObjectPath(object.path);
  };

  if (projectQuery.isLoading) return <ProjectLoading />;
  if (projectQuery.isError || !project) {
    return (
      <ProjectLoadError
        title={t.office.loadError}
        onRetry={() => void projectQuery.refetch()}
      />
    );
  }
  if (!revision) {
    if (revisionQuery.isLoading || revisionsQuery.isLoading) {
      return <ProjectLoading />;
    }
    return (
      <ProjectLoadError
        title={t.office.revisionLoadError}
        onRetry={() => {
          void revisionQuery.refetch();
          void revisionsQuery.refetch();
        }}
      />
    );
  }

  const evidence = renderEvidence[0];
  const hasComparison = !!revision.parent_revision_id;
  const hasChanges = hasComparison || !!generationReceipt;
  const originalThreadPath = project.primary_thread_id
    ? `/workspace/agents/office/chats/${project.primary_thread_id}`
    : null;

  return (
    <Tabs
      value={activeView}
      onValueChange={(value) =>
        setActiveView(value as "preview" | "compare" | "changes")
      }
      className="flex size-full min-w-0 flex-col overflow-hidden"
    >
      <header className="shrink-0 border-b">
        <div className="flex min-h-16 items-center justify-between gap-3 px-3 py-2 sm:px-5">
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger className="md:hidden" />
            <Button
              size="icon-sm"
              variant="ghost"
              asChild
              title={t.office.backToOffice}
            >
              <Link href="/workspace/office" aria-label={t.office.backToOffice}>
                <ArrowLeftIcon />
              </Link>
            </Button>
            <OfficeFormatIcon format={project.format} />
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <h1
                  className="truncate text-sm font-semibold sm:text-base"
                  title={project.title}
                >
                  {project.title}
                </h1>
                {!isCurrentRevision && (
                  <Badge
                    variant="outline"
                    className="hidden rounded-md sm:flex"
                  >
                    {t.office.historicalRevision}
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground truncate text-xs">
                {t.office.revision(revision.sequence)} /{" "}
                {readableBytes(revision.artifact.size_bytes)} /{" "}
                {formatTimeAgo(revision.created_at, locale)}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {project.template && (
              <Button variant="outline" size="sm" asChild>
                <Link
                  href={`/workspace/office/templates/${project.template.template_id}`}
                >
                  <LayoutTemplateIcon />
                  <span className="hidden lg:inline">
                    {t.office.templateVersion(project.template.version)}
                  </span>
                </Link>
              </Button>
            )}
            {originalThreadPath && (
              <Button variant="outline" size="sm" asChild>
                <Link href={originalThreadPath}>
                  <MessageSquareIcon />
                  <span className="hidden md:inline">
                    {t.office.continueInChat}
                  </span>
                </Link>
              </Button>
            )}
            <Button variant="outline" size="sm" asChild>
              <a
                href={officeArtifactURL(
                  project.project_id,
                  revision.revision_id,
                )}
                download
              >
                <DownloadIcon />
                <span className="hidden sm:inline">{t.common.download}</span>
              </a>
            </Button>
            <Button size="sm" asChild>
              <Link href="/workspace/agents/office/chats/new">
                <PlusIcon />
                <span className="hidden lg:inline">
                  {t.office.newOfficeChat}
                </span>
              </Link>
            </Button>
          </div>
        </div>
        <div className="flex min-h-12 items-center justify-between gap-3 overflow-x-auto border-t px-3 sm:px-5">
          <TabsList variant="line" className="h-12 shrink-0 rounded-none p-0">
            <TabsTrigger value="preview">{t.office.previewTab}</TabsTrigger>
            <TabsTrigger value="compare" disabled={!hasComparison}>
              {t.office.compareTab}
            </TabsTrigger>
            <TabsTrigger value="changes" disabled={!hasChanges}>
              {t.office.changesTab}
            </TabsTrigger>
          </TabsList>
          <OfficeProjectActions
            project={project}
            revision={revision}
            renderSet={renderSet}
            isCurrentRevision={isCurrentRevision}
          />
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:overflow-hidden">
        <section
          className="flex min-h-[480px] min-w-0 shrink-0 flex-col lg:min-h-0"
          aria-label={t.office.renderEvidence}
        >
          {activeView === "compare" ? (
            comparisonQuery.data ? (
              <OfficeRevisionComparisonView comparison={comparisonQuery.data} />
            ) : comparisonQuery.isLoading ? (
              <div className="flex min-h-0 flex-1 items-center justify-center">
                <LoaderCircleIcon className="text-muted-foreground size-5 animate-spin" />
              </div>
            ) : (
              <Empty className="min-h-0 border-0">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <FileWarningIcon />
                  </EmptyMedia>
                  <EmptyTitle>{t.office.comparisonUnavailable}</EmptyTitle>
                </EmptyHeader>
                <EmptyContent>
                  <Button
                    variant="outline"
                    onClick={() => void comparisonQuery.refetch()}
                  >
                    <RefreshCwIcon />
                    {t.office.retry}
                  </Button>
                </EmptyContent>
              </Empty>
            )
          ) : activeView === "changes" ? (
            generationReceipt ? (
              <OfficeGenerationEvidenceView
                receipt={generationReceipt}
                preflight={generationPreflight ?? null}
              />
            ) : comparisonQuery.data ? (
              <OfficeSemanticChangesView
                receipt={comparisonQuery.data.operation_receipt}
              />
            ) : comparisonQuery.isLoading ? (
              <div className="flex min-h-0 flex-1 items-center justify-center">
                <LoaderCircleIcon className="text-muted-foreground size-5 animate-spin" />
              </div>
            ) : (
              <Empty className="min-h-0 border-0">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <FileWarningIcon />
                  </EmptyMedia>
                  <EmptyTitle>{t.office.revisionLoadError}</EmptyTitle>
                </EmptyHeader>
              </Empty>
            )
          ) : (
            <>
              <div className="flex h-11 shrink-0 items-center justify-between border-b px-4 text-sm">
                <span className="font-medium">
                  {selectedPage
                    ? t.office.page(selectedPage.page, pageCount)
                    : t.office.noPreview}
                </span>
                <span className="text-muted-foreground flex items-center gap-2 text-xs">
                  {!isCurrentRevision && revisionQuery.isFetching && (
                    <LoaderCircleIcon className="size-3.5 animate-spin" />
                  )}
                  {evidence && t.office.pagesRendered(pages.length, pageCount)}
                </span>
              </div>

              {!isCurrentRevision && revisionQuery.isError ? (
                <Empty className="min-h-0 border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <FileWarningIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t.office.revisionLoadError}</EmptyTitle>
                  </EmptyHeader>
                  <EmptyContent>
                    <Button
                      variant="outline"
                      onClick={() => void revisionQuery.refetch()}
                    >
                      <RefreshCwIcon />
                      {t.office.retry}
                    </Button>
                  </EmptyContent>
                </Empty>
              ) : selectedPage ? (
                <div className="flex min-h-0 flex-1">
                  <aside
                    className="bg-muted/20 w-24 shrink-0 overflow-y-auto border-r p-2 sm:w-28"
                    aria-label={t.office.page(selectedPage.page, pageCount)}
                  >
                    <div className="space-y-2">
                      {pages.map((page) => (
                        <button
                          type="button"
                          key={`${page.sha256}-${page.page}`}
                          onClick={() => setSelectedPageNumber(page.page)}
                          aria-label={t.office.page(page.page, pageCount)}
                          aria-pressed={page.page === selectedPage.page}
                          className={cn(
                            "focus-visible:ring-ring w-full overflow-hidden rounded-md border bg-white p-1 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none dark:bg-neutral-100",
                            page.page === selectedPage.page
                              ? "border-primary ring-primary ring-1"
                              : "hover:border-foreground/30",
                          )}
                        >
                          <OfficePreviewImage
                            preview={page}
                            alt={t.office.previewAlt(project.title, page.page)}
                            className="aspect-[4/3] w-full object-contain"
                          />
                          <span className="block pt-1 text-center text-[10px] text-neutral-700">
                            {page.page}
                          </span>
                        </button>
                      ))}
                    </div>
                  </aside>
                  <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center overflow-auto bg-neutral-200/55 p-4 sm:p-6 dark:bg-neutral-950/55">
                    <div
                      className="relative max-h-full max-w-full overflow-hidden bg-white shadow-sm"
                      style={{
                        aspectRatio: `${selectedPage.width} / ${selectedPage.height}`,
                        width:
                          selectedPage.width >= selectedPage.height
                            ? "min(100%, 980px)"
                            : "min(72%, 720px)",
                      }}
                    >
                      <OfficePreviewImage
                        priority
                        preview={selectedPage}
                        alt={t.office.previewAlt(
                          project.title,
                          selectedPage.page,
                        )}
                        className="size-full"
                      />
                      {selectionQuery.data && (
                        <OfficeObjectOverlay
                          objects={selectionQuery.data.objects}
                          selectedPath={selectedObjectPath}
                          onSelect={handleObjectSelect}
                        />
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <Empty className="min-h-0 border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <FileWarningIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t.office.noPreview}</EmptyTitle>
                  </EmptyHeader>
                  <EmptyContent>
                    <Button asChild>
                      <Link href="/workspace/agents/office/chats/new">
                        <MessageSquareIcon />
                        {t.office.newOfficeChat}
                      </Link>
                    </Button>
                  </EmptyContent>
                </Empty>
              )}
            </>
          )}
        </section>

        <aside
          className="bg-background min-h-0 border-t lg:overflow-y-auto lg:border-t-0 lg:border-l"
          aria-label={t.office.projectDetails}
        >
          {project.format === "pptx" && activeView === "preview" && (
            <OfficeObjectSelectionPanel
              surface={selectionQuery.data}
              isLoading={selectionQuery.isLoading}
              isError={selectionQuery.isError}
              selectedPath={selectedObjectPath}
              isCurrentRevision={isCurrentRevision}
              onSelect={handleObjectSelect}
              onClear={() => setSelectedObjectPath(null)}
              onRetry={() => void selectionQuery.refetch()}
            />
          )}
          <section className="border-b p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">{t.office.visualReview}</h2>
              <Badge
                variant={
                  revision.quality.visual_review_status === "reviewed"
                    ? "default"
                    : "secondary"
                }
                className="rounded-md"
              >
                {revision.quality.visual_review_status === "reviewed" && (
                  <CheckCircle2Icon />
                )}
                {statusLabel(revision.quality.visual_review_status, t)}
              </Badge>
            </div>
            <dl className="divide-y">
              <QualityRow
                label={t.office.packageValidation}
                value={statusLabel(
                  revision.quality.package_validation_status,
                  t,
                )}
              />
              <QualityRow
                label={t.office.preflight}
                value={statusLabel(revision.quality.preflight_status, t)}
              />
              <QualityRow
                label={t.office.renderEvidence}
                value={statusLabel(revision.quality.render_evidence_status, t)}
              />
            </dl>
          </section>

          <section className="border-b p-4">
            <h2 className="mb-3 text-sm font-semibold">
              {t.office.sourceHash}
            </h2>
            <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] leading-5 break-all">
              {revision.artifact.sha256}
            </p>
          </section>

          <section className="border-b p-4">
            <h2 className="mb-2 text-sm font-semibold">
              {isCurrentRevision
                ? t.office.currentRevision
                : t.office.historicalRevision}
            </h2>
            <dl className="divide-y">
              {revision.kind === "generation" ? (
                <>
                  <QualityRow
                    label={t.office.generatedSlides}
                    value={String(revision.generation_slide_count)}
                  />
                  <QualityRow
                    label={t.office.generatedObjects}
                    value={String(revision.generation_object_count)}
                  />
                </>
              ) : (
                <>
                  <QualityRow
                    label={t.office.operations}
                    value={String(revision.operation_count)}
                  />
                  <QualityRow
                    label={t.office.changedObjects}
                    value={String(revision.changed_target_count)}
                  />
                  <QualityRow
                    label={t.office.packageChanges}
                    value={String(revision.part_change_count)}
                  />
                  <QualityRow
                    label={t.office.relationshipChanges}
                    value={String(revision.relationship_change_count)}
                  />
                </>
              )}
            </dl>
          </section>

          <section className="p-4">
            <div className="mb-1 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">
                {t.office.revisionHistory}
              </h2>
              {revisionsQuery.isFetching && (
                <RefreshCwIcon className="text-muted-foreground size-3.5 animate-spin" />
              )}
            </div>
            {revisionsQuery.data?.revisions.map((item) => (
              <RevisionRow
                key={item.revision_id}
                revision={item}
                current={
                  item.revision_id === project.current_revision.revision_id
                }
                selected={item.revision_id === revision.revision_id}
                onSelect={() => {
                  const projectPath = `/workspace/office/projects/${project.project_id}`;
                  router.push(
                    item.revision_id === project.current_revision.revision_id
                      ? projectPath
                      : `${projectPath}/revisions/${item.revision_id}`,
                  );
                }}
              />
            ))}
            {revisionsQuery.isError && (
              <Button
                variant="ghost"
                size="sm"
                className="mt-2"
                onClick={() => void revisionsQuery.refetch()}
              >
                <RefreshCwIcon />
                {t.office.retry}
              </Button>
            )}
          </section>

          {evidence && (
            <section className="text-muted-foreground border-t p-4 text-xs">
              <div className="flex items-center gap-1.5">
                <ExternalLinkIcon className="size-3.5" />
                <span>
                  {evidence.renderer} {evidence.renderer_version}
                </span>
              </div>
            </section>
          )}
        </aside>
      </main>
    </Tabs>
  );
}

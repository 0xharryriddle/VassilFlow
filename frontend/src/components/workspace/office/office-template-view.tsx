"use client";

import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  DownloadIcon,
  FilePlus2Icon,
  FileWarningIcon,
  ImageIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  PresentationIcon,
  RefreshCwIcon,
  ScanEyeIcon,
  SendIcon,
  ShieldCheckIcon,
  TextCursorInputIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  officeTemplateSourceURL,
  type OfficeTemplateCandidate,
  type OfficeTemplateSlotDraft,
  type OfficeTemplateVersionDetail,
  useOfficeTemplate,
  useOfficeTemplateVersion,
  usePublishOfficeTemplate,
  useRenderOfficeTemplate,
  useReviewOfficeTemplateRender,
  useUpdateOfficeTemplateSlots,
} from "@/core/office";
import { cn } from "@/lib/utils";

import { OfficePreviewImage } from "./office-preview-image";

type SlotFormState = OfficeTemplateSlotDraft & { enabled: boolean };

function readableBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function candidateSource(candidate: OfficeTemplateCandidate): string | null {
  const value =
    candidate.type === "text"
      ? candidate.source.text
      : (candidate.source.name ?? candidate.source.content_type);
  return typeof value === "string" && value ? value : null;
}

function baseSlotKey(candidate: OfficeTemplateCandidate): string {
  const normalized = candidate.default_label
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 56);
  const prefix = candidate.type === "text" ? "text" : "picture";
  return /^[a-z]/.test(normalized)
    ? normalized || `${prefix}_${candidate.slide_index}`
    : `${prefix}_${normalized || candidate.slide_index}`;
}

function uniqueSlotKey(
  candidate: OfficeTemplateCandidate,
  slots: Record<string, SlotFormState>,
): string {
  const base = baseSlotKey(candidate);
  const used = new Set(
    Object.values(slots)
      .filter((slot) => slot.enabled)
      .map((slot) => slot.key),
  );
  if (!used.has(base)) return base;
  let suffix = 2;
  while (used.has(`${base.slice(0, 61)}_${suffix}`)) suffix += 1;
  return `${base.slice(0, 61)}_${suffix}`;
}

function buildSlotForm(
  version: OfficeTemplateVersionDetail,
): Record<string, SlotFormState> {
  const saved = new Map(version.slots.map((slot) => [slot.candidate_id, slot]));
  return Object.fromEntries(
    version.slot_candidates.map((candidate) => {
      const slot = saved.get(candidate.candidate_id);
      return [
        candidate.candidate_id,
        {
          enabled: !!slot,
          candidate_id: candidate.candidate_id,
          type: candidate.type,
          key: slot?.key ?? baseSlotKey(candidate),
          label: slot?.label ?? candidate.default_label,
          required: slot?.required ?? true,
          max_length:
            candidate.type === "text"
              ? Number(slot?.constraints.max_length ?? 4000)
              : undefined,
        },
      ];
    }),
  );
}

function statusLabel(
  status: string,
  t: ReturnType<typeof useI18n>["t"],
): string {
  switch (status) {
    case "valid":
      return t.office.valid;
    case "available":
      return t.office.available;
    case "reviewed":
      return t.office.reviewed;
    case "external_review_required":
      return t.office.externalReviewRequired;
    case "not_performed":
      return t.office.notPerformed;
    case "not_recorded":
      return t.office.notRecorded;
    default:
      return t.office.unknownStatus;
  }
}

function TemplateLoading() {
  return (
    <div className="flex size-full flex-col">
      <div className="flex h-16 items-center gap-3 border-b px-4 sm:px-6">
        <Skeleton className="size-8 rounded-md" />
        <Skeleton className="h-5 w-56" />
      </div>
      <div className="mx-auto grid w-full max-w-7xl gap-6 p-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Skeleton className="aspect-video w-full" />
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    </div>
  );
}

function TemplateLoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex size-full flex-col">
      <header className="flex h-16 items-center gap-2 border-b px-4 sm:px-6">
        <SidebarTrigger className="md:hidden" />
        <Button variant="ghost" asChild>
          <Link href="/workspace/office/templates">
            <ArrowLeftIcon />
            {t.office.backToTemplates}
          </Link>
        </Button>
      </header>
      <Empty className="border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileWarningIcon />
          </EmptyMedia>
          <EmptyTitle>{t.office.templateLoadError}</EmptyTitle>
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

function QualityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="max-w-[62%] text-right font-medium break-words">
        {value}
      </dd>
    </div>
  );
}

export function OfficeTemplateView() {
  const { template_id: templateId } = useParams<{ template_id: string }>();
  const { t } = useI18n();
  const templateQuery = useOfficeTemplate(templateId);
  const template = templateQuery.data;
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  useEffect(() => {
    if (!template) return;
    const available = new Set(template.versions.map((item) => item.version));
    setSelectedVersion((current) =>
      current !== null && available.has(current)
        ? current
        : template.active_version.version,
    );
  }, [template]);

  const versionQuery = useOfficeTemplateVersion(templateId, selectedVersion);
  const version = versionQuery.data;
  const [slotForm, setSlotForm] = useState<Record<string, SlotFormState>>({});
  const [selectedPage, setSelectedPage] = useState<number | null>(null);

  useEffect(() => {
    if (!version) return;
    setSlotForm(buildSlotForm(version));
    setSelectedPage((current) =>
      version.render.preview_pages.some((page) => page.page === current)
        ? current
        : (version.render.preview_pages[0]?.page ?? null),
    );
  }, [version]);

  const updateSlots = useUpdateOfficeTemplateSlots();
  const renderTemplate = useRenderOfficeTemplate();
  const reviewRender = useReviewOfficeTemplateRender();
  const publishTemplate = usePublishOfficeTemplate();
  const isMutating =
    updateSlots.isPending ||
    renderTemplate.isPending ||
    reviewRender.isPending ||
    publishTemplate.isPending;
  const enabledSlots = useMemo(
    () => Object.values(slotForm).filter((slot) => slot.enabled),
    [slotForm],
  );

  if (templateQuery.isLoading) return <TemplateLoading />;
  if (templateQuery.isError || !template) {
    return <TemplateLoadError onRetry={() => void templateQuery.refetch()} />;
  }
  if (!selectedVersion || versionQuery.isLoading || !version) {
    return <TemplateLoading />;
  }
  if (versionQuery.isError) {
    return <TemplateLoadError onRetry={() => void versionQuery.refetch()} />;
  }

  const isDraft = version.status === "draft";
  const pages = version.render.preview_pages;
  const currentPage =
    pages.find((page) => page.page === selectedPage) ?? pages[0];
  const hasCompleteRender =
    version.render.status === "available" &&
    version.render.rendered_page_count === version.slide_count;
  const canPublish =
    isDraft &&
    version.slots.length > 0 &&
    hasCompleteRender &&
    version.render.visual_review_status === "reviewed";
  const preflightSummary =
    version.preflight_finding_count === 0
      ? t.office.noFindings
      : t.office.findings(version.preflight_finding_count);
  const versionNumber = version.version;
  const currentEvidenceId = version.render.evidence_id;

  function updateSlot(candidateId: string, patch: Partial<SlotFormState>) {
    setSlotForm((current) => {
      const slot = current[candidateId];
      if (!slot) return current;
      return {
        ...current,
        [candidateId]: { ...slot, ...patch },
      };
    });
  }

  function toggleSlot(candidate: OfficeTemplateCandidate, enabled: boolean) {
    setSlotForm((current) => {
      const slot = current[candidate.candidate_id];
      if (!slot) return current;
      return {
        ...current,
        [candidate.candidate_id]: {
          ...slot,
          enabled,
          key:
            enabled && !slot.enabled
              ? uniqueSlotKey(candidate, current)
              : slot.key,
        },
      };
    });
  }

  async function saveMapping() {
    const slots = enabledSlots.map(({ enabled: _enabled, ...slot }) => ({
      ...slot,
      max_length: slot.type === "text" ? slot.max_length : undefined,
    }));
    const keys = slots.map((slot) => slot.key);
    if (
      slots.some(
        (slot) =>
          !/^[a-z][a-z0-9_]{0,63}$/.test(slot.key) || !slot.label.trim(),
      ) ||
      new Set(keys).size !== keys.length
    ) {
      toast.error(t.office.mappingInvalid);
      return;
    }
    try {
      await updateSlots.mutateAsync({
        templateId,
        version: versionNumber,
        slots,
      });
      toast.success(t.office.mappingSaved);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.templateActionFailed,
      );
    }
  }

  async function renderAllSlides() {
    try {
      await renderTemplate.mutateAsync({
        templateId,
        version: versionNumber,
      });
      toast.success(t.office.renderComplete);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.templateActionFailed,
      );
    }
  }

  async function review(status: "reviewed" | "external_review_required") {
    if (!currentEvidenceId) return;
    try {
      await reviewRender.mutateAsync({
        templateId,
        version: versionNumber,
        evidenceId: currentEvidenceId,
        status,
      });
      toast.success(t.office.reviewSaved);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.templateActionFailed,
      );
    }
  }

  async function publish() {
    try {
      await publishTemplate.mutateAsync({
        templateId,
        version: versionNumber,
      });
      toast.success(t.office.templatePublished);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.templateActionFailed,
      );
    }
  }

  return (
    <div className="flex size-full min-w-0 flex-col overflow-hidden">
      <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b px-3 py-2 sm:px-5">
        <div className="flex min-w-0 items-center gap-2">
          <SidebarTrigger className="md:hidden" />
          <Button
            size="icon-sm"
            variant="ghost"
            asChild
            title={t.office.backToTemplates}
          >
            <Link
              href="/workspace/office/templates"
              aria-label={t.office.backToTemplates}
            >
              <ArrowLeftIcon />
            </Link>
          </Button>
          <PresentationIcon className="text-muted-foreground size-5 shrink-0" />
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h1
                className="truncate text-sm font-semibold sm:text-base"
                title={template.title}
              >
                {template.title}
              </h1>
              <Badge
                variant={isDraft ? "secondary" : "default"}
                className="hidden rounded-md sm:flex"
              >
                {isDraft ? t.office.draft : t.office.published}
              </Badge>
            </div>
            <p className="text-muted-foreground truncate text-xs">
              {version.filename} / {readableBytes(version.source.size_bytes)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Select
            value={String(selectedVersion)}
            onValueChange={(value) => setSelectedVersion(Number(value))}
            disabled={isMutating}
          >
            <SelectTrigger size="sm" aria-label={t.office.versionHistory}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {template.versions.map((item) => (
                <SelectItem key={item.version} value={String(item.version)}>
                  {t.office.version(item.version)} /{" "}
                  {item.status === "draft"
                    ? t.office.draft
                    : t.office.published}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" asChild>
            <a
              href={officeTemplateSourceURL(templateId, version.version)}
              download
            >
              <DownloadIcon />
              <span className="hidden sm:inline">
                {t.office.downloadSource}
              </span>
            </a>
          </Button>
          {!isDraft && (
            <Button size="sm" asChild>
              <Link
                href={`/workspace/office/templates/${templateId}/use?version=${version.version}`}
              >
                <FilePlus2Icon />
                <span className="hidden sm:inline">{t.office.useTemplate}</span>
              </Link>
            </Button>
          )}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-[1500px] gap-0 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 xl:border-r">
            <section aria-labelledby="template-preview-heading">
              <div className="flex min-h-11 items-center justify-between gap-3 border-b px-4 py-2 sm:px-6">
                <h2
                  id="template-preview-heading"
                  className="text-sm font-semibold"
                >
                  {t.common.preview}
                </h2>
                <span className="text-muted-foreground text-xs">
                  {hasCompleteRender
                    ? t.office.pagesRendered(pages.length, version.slide_count)
                    : t.office.renderRequired}
                </span>
              </div>

              {currentPage ? (
                <div className="flex h-[min(62vh,680px)] min-h-[420px]">
                  <aside
                    className="bg-muted/20 w-24 shrink-0 overflow-y-auto border-r p-2 sm:w-28"
                    aria-label={t.office.slides(version.slide_count)}
                  >
                    <div className="space-y-2">
                      {pages.map((page) => (
                        <button
                          type="button"
                          key={`${page.sha256}-${page.page}`}
                          onClick={() => setSelectedPage(page.page)}
                          aria-label={t.office.page(
                            page.page,
                            version.slide_count,
                          )}
                          aria-pressed={page.page === currentPage.page}
                          className={cn(
                            "focus-visible:ring-ring w-full overflow-hidden rounded-md border bg-white p-1 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none dark:bg-neutral-100",
                            page.page === currentPage.page
                              ? "border-primary ring-primary ring-1"
                              : "hover:border-foreground/30",
                          )}
                        >
                          <OfficePreviewImage
                            preview={page}
                            alt={t.office.previewAlt(template.title, page.page)}
                            className="aspect-video w-full object-contain"
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
                      className="relative max-h-full w-full max-w-[980px] overflow-hidden bg-white shadow-sm"
                      style={{
                        aspectRatio: `${currentPage.width} / ${currentPage.height}`,
                      }}
                    >
                      <OfficePreviewImage
                        priority
                        preview={currentPage}
                        alt={t.office.previewAlt(
                          template.title,
                          currentPage.page,
                        )}
                        className="size-full"
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <Empty className="min-h-[420px] border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ScanEyeIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t.office.noTemplatePreview}</EmptyTitle>
                    <EmptyDescription>
                      {t.office.renderRequired}
                    </EmptyDescription>
                  </EmptyHeader>
                  {isDraft && (
                    <EmptyContent>
                      <Button
                        onClick={() => void renderAllSlides()}
                        disabled={renderTemplate.isPending}
                      >
                        {renderTemplate.isPending ? (
                          <LoaderCircleIcon className="animate-spin" />
                        ) : (
                          <ScanEyeIcon />
                        )}
                        {renderTemplate.isPending
                          ? t.office.rendering
                          : t.office.renderAllSlides}
                      </Button>
                    </EmptyContent>
                  )}
                </Empty>
              )}
            </section>

            <section
              className="border-t"
              aria-labelledby="template-mapping-heading"
            >
              <div className="flex flex-col gap-3 border-b px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div>
                  <h2
                    id="template-mapping-heading"
                    className="text-sm font-semibold"
                  >
                    {t.office.mapping}
                  </h2>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t.office.mappingDescription}
                  </p>
                </div>
                {isDraft && (
                  <Button
                    size="sm"
                    onClick={() => void saveMapping()}
                    disabled={updateSlots.isPending}
                  >
                    {updateSlots.isPending ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : (
                      <ShieldCheckIcon />
                    )}
                    {t.office.saveMapping}
                  </Button>
                )}
              </div>

              {version.slot_candidates.length === 0 ? (
                <Empty className="min-h-64 border-0">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <LockKeyholeIcon />
                    </EmptyMedia>
                    <EmptyTitle>{t.office.noSlotCandidates}</EmptyTitle>
                    <EmptyDescription>
                      {t.office.noSlotCandidatesDescription}
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <div className="divide-y">
                  {version.slot_candidates.map((candidate) => {
                    const slot = slotForm[candidate.candidate_id];
                    const Icon =
                      candidate.type === "text"
                        ? TextCursorInputIcon
                        : ImageIcon;
                    const source = candidateSource(candidate);
                    return (
                      <div
                        key={candidate.candidate_id}
                        className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(180px,0.9fr)_minmax(0,1.6fr)] sm:px-6"
                      >
                        <div className="flex min-w-0 items-start gap-3">
                          <span className="bg-muted mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md">
                            <Icon className="size-4" />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <p className="truncate text-sm font-medium">
                                {candidate.default_label}
                              </p>
                              <Badge variant="outline" className="rounded-md">
                                {candidate.type === "text"
                                  ? t.office.textSlot
                                  : t.office.pictureSlot}
                              </Badge>
                            </div>
                            <p className="text-muted-foreground mt-1 text-xs">
                              {t.office.slotCandidate(candidate.slide_index)}
                            </p>
                            {source && (
                              <p
                                className="text-muted-foreground mt-1 line-clamp-2 text-xs"
                                title={source}
                              >
                                {source}
                              </p>
                            )}
                            <p
                              className="text-muted-foreground mt-1 truncate font-mono text-[10px]"
                              title={candidate.path}
                            >
                              {candidate.path}
                            </p>
                          </div>
                          <Switch
                            checked={slot?.enabled ?? false}
                            onCheckedChange={(checked) =>
                              toggleSlot(candidate, checked)
                            }
                            disabled={!isDraft || isMutating}
                            aria-label={t.office.enableSlot(
                              candidate.default_label,
                            )}
                          />
                        </div>

                        {slot?.enabled ? (
                          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                            <label className="min-w-0 space-y-1.5 text-xs font-medium">
                              <span>{t.office.slotKey}</span>
                              <Input
                                value={slot.key}
                                onChange={(event) =>
                                  updateSlot(candidate.candidate_id, {
                                    key: event.target.value,
                                  })
                                }
                                maxLength={64}
                                disabled={!isDraft || isMutating}
                                className="font-mono text-xs"
                              />
                            </label>
                            <label className="min-w-0 space-y-1.5 text-xs font-medium">
                              <span>{t.office.slotLabel}</span>
                              <Input
                                value={slot.label}
                                onChange={(event) =>
                                  updateSlot(candidate.candidate_id, {
                                    label: event.target.value,
                                  })
                                }
                                maxLength={120}
                                disabled={!isDraft || isMutating}
                              />
                            </label>
                            {candidate.type === "text" && (
                              <label className="min-w-0 space-y-1.5 text-xs font-medium">
                                <span>{t.office.maxLength}</span>
                                <Input
                                  type="number"
                                  min={1}
                                  max={4000}
                                  value={slot.max_length ?? 4000}
                                  onChange={(event) =>
                                    updateSlot(candidate.candidate_id, {
                                      max_length: Number(event.target.value),
                                    })
                                  }
                                  disabled={!isDraft || isMutating}
                                />
                              </label>
                            )}
                            <label className="flex min-h-9 items-center justify-between gap-3 self-end rounded-md border px-3 text-xs font-medium">
                              <span>{t.office.required}</span>
                              <Switch
                                checked={slot.required}
                                onCheckedChange={(checked) =>
                                  updateSlot(candidate.candidate_id, {
                                    required: checked,
                                  })
                                }
                                disabled={!isDraft || isMutating}
                                aria-label={`${t.office.required}: ${candidate.default_label}`}
                              />
                            </label>
                          </div>
                        ) : (
                          <div className="text-muted-foreground flex min-h-9 items-center text-xs">
                            {t.office.allOtherObjectsLocked}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </div>

          <aside className="min-w-0 xl:min-h-[calc(100vh-4rem)]">
            <section className="border-b p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold">{t.office.qaStatus}</h2>
                <Badge
                  variant={
                    version.render.visual_review_status === "reviewed"
                      ? "default"
                      : "secondary"
                  }
                  className="rounded-md"
                >
                  {version.render.visual_review_status === "reviewed" && (
                    <CheckCircle2Icon />
                  )}
                  {statusLabel(version.render.visual_review_status, t)}
                </Badge>
              </div>
              <dl className="divide-y">
                <QualityRow
                  label={t.office.packageValidation}
                  value={statusLabel(version.validation_status, t)}
                />
                <QualityRow
                  label={t.office.preflight}
                  value={preflightSummary}
                />
                <QualityRow
                  label={t.office.renderEvidence}
                  value={
                    hasCompleteRender
                      ? t.office.pagesRendered(
                          version.render.rendered_page_count,
                          version.slide_count,
                        )
                      : statusLabel(version.render.status, t)
                  }
                />
                <QualityRow
                  label={t.office.mapping}
                  value={t.office.slots(version.slots.length)}
                />
              </dl>
            </section>

            <section className="space-y-3 border-b p-4">
              <div>
                <h2 className="text-sm font-semibold">
                  {t.office.visualReview}
                </h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  {t.office.reviewCurrentEvidence}
                </p>
              </div>
              {isDraft && (
                <div className="grid gap-2">
                  <Button
                    variant="outline"
                    onClick={() => void renderAllSlides()}
                    disabled={renderTemplate.isPending || isMutating}
                  >
                    {renderTemplate.isPending ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : (
                      <ScanEyeIcon />
                    )}
                    {renderTemplate.isPending
                      ? t.office.rendering
                      : t.office.renderAllSlides}
                  </Button>
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void review("reviewed")}
                      disabled={!hasCompleteRender || isMutating}
                    >
                      <CheckCircle2Icon />
                      {t.office.markReviewed}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void review("external_review_required")}
                      disabled={!hasCompleteRender || isMutating}
                    >
                      <SendIcon />
                      {t.office.requestExternalReview}
                    </Button>
                  </div>
                </div>
              )}
            </section>

            <section className="space-y-3 border-b p-4">
              <div className="flex items-start gap-2">
                <LockKeyholeIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <div>
                  <h2 className="text-sm font-semibold">
                    {t.office.fixedStructure}
                  </h2>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t.office.allOtherObjectsLocked}
                  </p>
                </div>
              </div>
              {isDraft && (
                <>
                  {!canPublish && (
                    <Alert>
                      <AlertTitle>
                        {t.office.publishRequirementsTitle}
                      </AlertTitle>
                      <AlertDescription>
                        {t.office.publishRequirements}
                      </AlertDescription>
                    </Alert>
                  )}
                  <Button
                    className="w-full"
                    onClick={() => void publish()}
                    disabled={!canPublish || isMutating}
                  >
                    {publishTemplate.isPending ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : (
                      <ShieldCheckIcon />
                    )}
                    {publishTemplate.isPending
                      ? t.office.publishing
                      : t.office.publishTemplate}
                  </Button>
                </>
              )}
            </section>

            <section className="p-4">
              <h2 className="mb-2 text-sm font-semibold">
                {t.office.sourceHash}
              </h2>
              <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] leading-5 break-all">
                {version.source.sha256}
              </p>
            </section>
          </aside>
        </div>
      </main>
    </div>
  );
}

"use client";

import { FileWarningIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { useI18n } from "@/core/i18n/hooks";
import {
  collectOfficePreviewPages,
  type OfficeChangeReceipt,
  type OfficeGenerationPreflight,
  type OfficeGenerationReceipt,
  type OfficeRevisionComparison,
} from "@/core/office";
import { cn } from "@/lib/utils";

import { OfficePreviewImage } from "./office-preview-image";

function receiptValue(value: unknown): string {
  if (typeof value === "string") return value;
  const serialized = JSON.stringify(value);
  if (!serialized) return String(value);
  return serialized.length > 320
    ? `${serialized.slice(0, 317)}...`
    : serialized;
}

function readableBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function OfficeGenerationEvidenceView({
  receipt,
  preflight,
}: {
  receipt: OfficeGenerationReceipt;
  preflight: OfficeGenerationPreflight | null;
}) {
  const { t } = useI18n();

  return (
    <div
      data-testid="office-generation-evidence"
      className="flex-none overflow-visible lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
    >
      <section className="bg-border grid gap-px border-b sm:grid-cols-2 lg:grid-cols-4">
        {[
          [
            t.office.compiler,
            `${receipt.compiler.id} v${receipt.compiler.version}`,
          ],
          [t.office.generatedSlides, String(receipt.presentation.slide_count)],
          [
            t.office.generatedObjects,
            String(receipt.presentation.object_count),
          ],
          [t.office.staticFindings, String(preflight?.finding_count ?? 0)],
        ].map(([label, value]) => (
          <div key={label} className="bg-background min-w-0 p-4 sm:p-5">
            <p className="text-muted-foreground text-xs">{label}</p>
            <p className="mt-1 text-sm font-semibold break-words" title={value}>
              {value}
            </p>
          </div>
        ))}
      </section>

      <section className="grid gap-4 border-b p-4 sm:grid-cols-2 sm:p-6">
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">
            {t.office.intentHash}
          </p>
          <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
            {receipt.intent.sha256}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {readableBytes(receipt.intent.size_bytes)} / {receipt.intent.schema}
          </p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">
            {t.office.outputHash}
          </p>
          <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
            {receipt.output.sha256}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {readableBytes(receipt.output.size_bytes)} /{" "}
            {receipt.presentation.aspect_ratio}
          </p>
        </div>
      </section>

      <section className="border-b px-4 py-5 sm:px-6">
        <h2 className="text-sm font-semibold">{t.office.generationEvidence}</h2>
        <div className="mt-3 divide-y border-y">
          {receipt.slides.map((slide) => (
            <article key={slide.slide_id} className="py-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {t.office.slideNumber(slide.slide_index)}
                  </p>
                  <p className="text-muted-foreground mt-0.5 text-xs">
                    {slide.purpose}
                  </p>
                </div>
                <Badge variant="secondary" className="rounded-md">
                  {slide.layout.replaceAll("_", " ")}
                </Badge>
              </div>
              <div className="mt-3 space-y-1.5">
                {slide.objects.map((object) => (
                  <div
                    key={object.element_id}
                    className="bg-muted/55 grid min-w-0 gap-1 px-2.5 py-2 text-xs sm:grid-cols-[minmax(100px,0.35fr)_minmax(0,1fr)]"
                  >
                    <span className="font-medium">
                      {object.element_id} / {object.role}
                    </span>
                    <span
                      className="truncate font-mono text-[11px]"
                      title={object.object_path}
                    >
                      {object.object_path}
                    </span>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      {receipt.assets.length > 0 && (
        <section className="p-4 sm:p-6">
          <h2 className="mb-3 text-sm font-semibold">
            {t.office.generationAssets}
          </h2>
          <div className="divide-y border-y">
            {receipt.assets.map((asset) => (
              <div
                key={asset.element_id}
                className="grid gap-2 py-3 text-xs sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)]"
              >
                <div>
                  <p className="font-medium">{asset.element_id}</p>
                  <p className="text-muted-foreground mt-0.5 uppercase">
                    {asset.format} / {asset.width_px}x{asset.height_px}
                  </p>
                </div>
                <p className="font-mono text-[11px] break-all">
                  {asset.sha256}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export function OfficeRevisionComparisonView({
  comparison,
}: {
  comparison: OfficeRevisionComparison;
}) {
  const { t } = useI18n();
  const beforePages = useMemo(
    () => collectOfficePreviewPages(comparison.before_render.evidence),
    [comparison.before_render.evidence],
  );
  const afterPages = useMemo(
    () => collectOfficePreviewPages(comparison.after_render.evidence),
    [comparison.after_render.evidence],
  );
  const commonPages = useMemo(
    () =>
      beforePages
        .map((page) => page.page)
        .filter((page) =>
          afterPages.some((candidate) => candidate.page === page),
        ),
    [afterPages, beforePages],
  );
  const [selectedPage, setSelectedPage] = useState(commonPages[0] ?? 1);

  useEffect(() => {
    if (!commonPages.includes(selectedPage)) {
      setSelectedPage(commonPages[0] ?? 1);
    }
  }, [commonPages, selectedPage]);

  const before = beforePages.find((page) => page.page === selectedPage);
  const after = afterPages.find((page) => page.page === selectedPage);
  if (!before || !after) {
    return (
      <Empty className="min-h-0 border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileWarningIcon />
          </EmptyMedia>
          <EmptyTitle>{t.office.comparisonUnavailable}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex h-12 shrink-0 items-center gap-1 overflow-x-auto border-b px-3">
        {commonPages.map((page) => (
          <Button
            key={page}
            variant={page === selectedPage ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setSelectedPage(page)}
            aria-pressed={page === selectedPage}
          >
            {page}
          </Button>
        ))}
      </div>
      <div className="grid min-h-0 flex-1 overflow-auto bg-neutral-200/55 lg:grid-cols-2 dark:bg-neutral-950/55">
        {(
          [
            [t.office.renderBefore, before],
            [t.office.renderAfter, after],
          ] as const
        ).map(([label, page], index) => (
          <section
            key={label}
            className={cn(
              "flex min-h-[360px] min-w-0 flex-col p-4 sm:p-6",
              index === 0 && "border-b lg:border-r lg:border-b-0",
            )}
          >
            <h2 className="mb-3 text-xs font-semibold tracking-normal uppercase">
              {label}
            </h2>
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <div
                className="relative max-h-full max-w-full overflow-hidden bg-white shadow-sm"
                style={{
                  aspectRatio: `${page.width} / ${page.height}`,
                  width:
                    page.width >= page.height
                      ? "min(100%, 760px)"
                      : "min(72%, 560px)",
                }}
              >
                <OfficePreviewImage
                  preview={page}
                  alt={`${label}, ${t.office.page(page.page, commonPages.length)}`}
                  className="size-full"
                />
              </div>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

export function OfficeSemanticChangesView({
  receipt,
}: {
  receipt: OfficeChangeReceipt;
}) {
  const { t } = useI18n();
  const semantic = receipt.semantic_changes;
  const paths = Array.from(
    new Set(receipt.operations.flatMap((operation) => operation.target_paths)),
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <section className="grid gap-4 border-b p-4 sm:grid-cols-2 sm:p-6">
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">
            {t.office.before}
          </p>
          <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
            {receipt.source.sha256}
          </p>
        </div>
        <div className="min-w-0">
          <p className="text-muted-foreground mb-1 text-xs">{t.office.after}</p>
          <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
            {receipt.result.sha256}
          </p>
        </div>
      </section>

      <section className="grid gap-6 border-b p-4 sm:grid-cols-3 sm:p-6">
        <div>
          <p className="text-muted-foreground text-xs">
            {t.office.semanticCoverage}
          </p>
          <Badge variant="secondary" className="mt-2 rounded-md">
            {semantic.coverage === "complete"
              ? t.office.completeCoverage
              : t.office.partialCoverage}
          </Badge>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">{t.office.operations}</p>
          <p className="mt-2 text-lg font-semibold">
            {receipt.operation_count}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">
            {t.office.changedObjects}
          </p>
          <p className="mt-2 text-lg font-semibold">
            {semantic.changed_target_count}
          </p>
        </div>
      </section>

      <section className="grid gap-6 border-b p-4 sm:p-6 lg:grid-cols-2">
        <div className="min-w-0">
          <h2 className="mb-3 text-sm font-semibold">
            {t.office.operationIds}
          </h2>
          <div className="space-y-1.5">
            {receipt.applied_operation_ids.map((operationId) => (
              <p
                key={operationId}
                className="bg-muted truncate rounded-md px-2.5 py-2 font-mono text-[11px]"
                title={operationId}
              >
                {operationId}
              </p>
            ))}
          </div>
        </div>
        <div className="min-w-0">
          <h2 className="mb-3 text-sm font-semibold">{t.office.objectPaths}</h2>
          <div className="space-y-1.5">
            {paths.map((path) => (
              <p
                key={path}
                className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all"
              >
                {path}
              </p>
            ))}
          </div>
        </div>
      </section>

      <section className="p-4 sm:p-6">
        <h2 className="mb-3 text-sm font-semibold">{t.office.changeReceipt}</h2>
        {semantic.semantic_deltas.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.office.noSemanticChanges}
          </p>
        ) : (
          <div className="divide-y border-y">
            {semantic.semantic_deltas.map((delta, index) => (
              <div
                key={`${delta.path}-${delta.property}-${index}`}
                className="grid gap-3 py-4 lg:grid-cols-[minmax(180px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)]"
              >
                <div className="min-w-0">
                  <p className="font-mono text-[11px] break-all">
                    {delta.path}
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {delta.property}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="text-muted-foreground mb-1 text-xs">
                    {t.office.before}
                  </p>
                  <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
                    {receiptValue(delta.before)}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="text-muted-foreground mb-1 text-xs">
                    {t.office.after}
                  </p>
                  <p className="bg-muted rounded-md px-2.5 py-2 font-mono text-[11px] break-all">
                    {receiptValue(delta.after)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

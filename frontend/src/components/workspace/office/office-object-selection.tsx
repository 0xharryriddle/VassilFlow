"use client";

import {
  ImageIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  MousePointer2Icon,
  RefreshCwIcon,
  ShapesIcon,
  TypeIcon,
  WaypointsIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildOfficeObjectSelectionRequest,
  buildOfficeSelectionChatHref,
  type OfficePptxSelectionObject,
  type OfficePptxSelectionSurface,
} from "@/core/office";
import { cn } from "@/lib/utils";

function ObjectIcon({ kind }: { kind: string }) {
  if (kind === "picture") return <ImageIcon />;
  if (kind === "connector") return <WaypointsIcon />;
  if (["text_box", "title", "placeholder"].includes(kind)) {
    return <TypeIcon />;
  }
  return <ShapesIcon />;
}

export function officeObjectLabel(
  object: OfficePptxSelectionObject,
  unnamed: (kind: string) => string,
): string {
  const name = object.name?.trim();
  if (name) return name;
  const firstLine = object.text_preview.split("\n")[0]?.trim();
  if (firstLine) return firstLine;
  return unnamed(object.kind);
}

export function OfficeObjectOverlay({
  objects,
  selectedPath,
  onSelect,
}: {
  objects: OfficePptxSelectionObject[];
  selectedPath: string | null;
  onSelect: (object: OfficePptxSelectionObject) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="pointer-events-none absolute inset-0">
      {objects
        .filter(
          (object) =>
            object.selection_status === "selectable" && object.overlay,
        )
        .map((object) => {
          const overlay = object.overlay!;
          const label = officeObjectLabel(object, t.office.unnamedObject);
          const selected = object.path === selectedPath;
          return (
            <button
              key={object.path}
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              title={t.office.selectObject(label)}
              data-testid={`office-object-overlay-${object.object_fingerprint.slice(0, 8)}`}
              onClick={() => onSelect(object)}
              className={cn(
                "pointer-events-auto absolute border transition-colors",
                selected
                  ? "border-primary bg-primary/10 ring-primary ring-2"
                  : "border-transparent hover:border-sky-500 hover:bg-sky-400/10",
              )}
              style={{
                left: `${overlay.left_percent}%`,
                top: `${overlay.top_percent}%`,
                width: `${overlay.width_percent}%`,
                height: `${overlay.height_percent}%`,
                transform:
                  overlay.rotation_degrees === null
                    ? undefined
                    : `rotate(${overlay.rotation_degrees}deg)`,
                zIndex: selected ? 1000 : Math.max(1, object.z_order ?? 1),
              }}
            />
          );
        })}
    </div>
  );
}

export function OfficeObjectSelectionPanel({
  surface,
  isLoading,
  isError,
  selectedPath,
  isCurrentRevision,
  onSelect,
  onClear,
  onRetry,
}: {
  surface: OfficePptxSelectionSurface | undefined;
  isLoading: boolean;
  isError: boolean;
  selectedPath: string | null;
  isCurrentRevision: boolean;
  onSelect: (object: OfficePptxSelectionObject) => void;
  onClear: () => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const objects =
    surface?.objects.filter(
      (object) => object.selection_status === "selectable",
    ) ?? [];
  const selected = objects.find((object) => object.path === selectedPath);
  const selectedLabel = selected
    ? officeObjectLabel(selected, t.office.unnamedObject)
    : null;
  const chatHref =
    surface && selected
      ? buildOfficeSelectionChatHref(
          buildOfficeObjectSelectionRequest(surface, selected),
        )
      : null;

  return (
    <section className="border-b p-4" aria-label={t.office.objects}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t.office.objects}</h2>
        {surface && (
          <Badge variant="outline" className="rounded-md">
            {t.office.objectsOnSlide(objects.length, surface.slide.index)}
          </Badge>
        )}
      </div>

      {isLoading ? (
        <div className="text-muted-foreground flex items-center gap-2 py-3 text-xs">
          <LoaderCircleIcon className="size-3.5 animate-spin" />
          {t.office.objectSelectionLoading}
        </div>
      ) : isError ? (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs">
            {t.office.objectSelectionError}
          </p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCwIcon />
            {t.office.retry}
          </Button>
        </div>
      ) : objects.length === 0 ? (
        <div className="py-2">
          <p className="text-sm font-medium">{t.office.noSelectableObjects}</p>
          <p className="text-muted-foreground mt-1 text-xs">
            {t.office.noSelectableObjectsDescription}
          </p>
        </div>
      ) : (
        <div className="max-h-64 overflow-y-auto border-y">
          {objects.map((object) => {
            const label = officeObjectLabel(object, t.office.unnamedObject);
            const active = selectedPath === object.path;
            return (
              <button
                key={object.path}
                type="button"
                aria-pressed={active}
                aria-label={t.office.selectObject(label)}
                onClick={() => onSelect(object)}
                className={cn(
                  "focus-visible:ring-ring flex w-full items-start gap-2 border-b px-2 py-2.5 text-left last:border-b-0 focus-visible:ring-2 focus-visible:outline-none",
                  active ? "bg-muted" : "hover:bg-muted/45",
                )}
              >
                <span className="text-muted-foreground mt-0.5 [&>svg]:size-3.5">
                  <ObjectIcon kind={object.kind} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">
                    {label}
                  </span>
                  {object.text_preview && (
                    <span className="text-muted-foreground mt-0.5 block truncate text-[11px]">
                      {object.text_preview}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {selected && selectedLabel && (
        <div className="mt-3 space-y-2" data-testid="office-selected-object">
          <div className="flex items-center gap-2">
            <MousePointer2Icon className="text-primary size-3.5" />
            <span className="min-w-0 flex-1 truncate text-xs font-medium">
              {selectedLabel}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t.office.clearObjectSelection}
              title={t.office.clearObjectSelection}
              onClick={onClear}
            >
              <XIcon />
            </Button>
          </div>
          {isCurrentRevision && chatHref ? (
            <Button size="sm" className="w-full" asChild>
              <Link href={chatHref}>
                <MessageSquareIcon />
                {t.office.editSelectedObject}
              </Link>
            </Button>
          ) : (
            <p className="text-muted-foreground text-xs">
              {t.office.currentRevisionRequired}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

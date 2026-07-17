"use client";

import {
  FileWarningIcon,
  LoaderCircleIcon,
  MousePointer2Icon,
  XIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import type { OfficePptxSelectionObject } from "@/core/office";

import { officeObjectLabel } from "./office-object-selection";

export function OfficeSelectionChip({
  slide,
  object,
  loading,
  invalid,
  onClear,
}: {
  slide: number;
  object: OfficePptxSelectionObject | null;
  loading: boolean;
  invalid: boolean;
  onClear: () => void;
}) {
  const { t } = useI18n();
  const label = invalid
    ? t.office.objectSelectionError
    : object
      ? t.office.selectedObjectContext(
          slide,
          officeObjectLabel(object, t.office.unnamedObject),
        )
      : loading
        ? t.office.objectSelectionLoading
        : t.office.objectSelectionError;

  return (
    <div
      className="bg-muted/65 flex w-full min-w-0 items-center gap-2 rounded-md border px-2 py-1.5"
      data-testid="office-selection-chip"
    >
      {loading ? (
        <LoaderCircleIcon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
      ) : invalid ? (
        <FileWarningIcon className="text-destructive size-3.5 shrink-0" />
      ) : (
        <MousePointer2Icon className="text-primary size-3.5 shrink-0" />
      )}
      <span
        className="min-w-0 flex-1 truncate text-xs font-medium"
        title={label}
      >
        {label}
      </span>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        aria-label={t.office.clearObjectSelection}
        title={t.office.clearObjectSelection}
        onClick={onClear}
      >
        <XIcon />
      </Button>
    </div>
  );
}

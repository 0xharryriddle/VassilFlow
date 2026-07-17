import { FileTextIcon, PresentationIcon, SheetIcon } from "lucide-react";

import type { OfficeFormat } from "@/core/office";
import { cn } from "@/lib/utils";

const FORMAT_STYLES: Record<OfficeFormat, string> = {
  pptx: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
  docx: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  xlsx: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
};

export function OfficeFormatIcon({
  format,
  className,
}: {
  format: OfficeFormat;
  className?: string;
}) {
  const Icon =
    format === "pptx"
      ? PresentationIcon
      : format === "xlsx"
        ? SheetIcon
        : FileTextIcon;
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-md",
        FORMAT_STYLES[format],
        className,
      )}
    >
      <Icon className="size-4" />
    </span>
  );
}

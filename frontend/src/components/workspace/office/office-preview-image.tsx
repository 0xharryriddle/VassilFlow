import Image from "next/image";

import { officeResourceURL, type OfficePreviewPage } from "@/core/office";
import { cn } from "@/lib/utils";

export function OfficePreviewImage({
  preview,
  alt,
  className,
  priority = false,
}: {
  preview: OfficePreviewPage;
  alt: string;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      unoptimized
      priority={priority}
      src={officeResourceURL(preview.url)}
      alt={alt}
      width={preview.width}
      height={preview.height}
      className={cn("object-contain", className)}
    />
  );
}

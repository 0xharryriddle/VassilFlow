import type { OfficePreviewPage, OfficeRenderEvidence } from "./types";

export function collectOfficePreviewPages(
  evidence: OfficeRenderEvidence[],
): OfficePreviewPage[] {
  const newestByPage = new Map<number, OfficePreviewPage>();
  for (const record of evidence) {
    for (const page of record.preview_pages) {
      if (!newestByPage.has(page.page)) {
        newestByPage.set(page.page, page);
      }
    }
  }
  return Array.from(newestByPage.values()).sort((a, b) => a.page - b.page);
}

export function officePageCount(evidence: OfficeRenderEvidence[]): number {
  return evidence.reduce(
    (pageCount, record) => Math.max(pageCount, record.page_count),
    0,
  );
}

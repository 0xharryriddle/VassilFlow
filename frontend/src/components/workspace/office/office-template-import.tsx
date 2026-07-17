"use client";

import {
  ArrowLeftIcon,
  FileUpIcon,
  LoaderCircleIcon,
  PresentationIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useImportOfficeTemplate } from "@/core/office";

const MAX_TEMPLATE_BYTES = 50 * 1024 * 1024;

function readableBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function OfficeTemplateImport() {
  const { t } = useI18n();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const importTemplate = useImportOfficeTemplate();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  function selectFile(selected: File | null) {
    setValidationError(null);
    if (!selected) {
      setFile(null);
      return;
    }
    if (!selected.name.toLocaleLowerCase().endsWith(".pptx")) {
      setFile(null);
      setValidationError(t.office.pptxRequired);
      return;
    }
    if (selected.size > MAX_TEMPLATE_BYTES) {
      setFile(null);
      setValidationError(t.office.fileTooLarge);
      return;
    }
    setFile(selected);
    if (!title.trim()) {
      setTitle(selected.name.replace(/\.pptx$/i, ""));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setValidationError(t.office.pptxRequired);
      return;
    }
    try {
      const template = await importTemplate.mutateAsync({
        file,
        title: title.trim() || undefined,
      });
      router.replace(`/workspace/office/templates/${template.template_id}`);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.importFailed,
      );
    }
  }

  return (
    <div className="flex size-full min-w-0 flex-col">
      <header className="flex min-h-16 shrink-0 items-center gap-2 border-b px-3 py-2 sm:px-5">
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
        <h1 className="truncate text-base font-semibold sm:text-lg">
          {t.office.importTemplateTitle}
        </h1>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="mx-auto w-full max-w-2xl space-y-6"
        >
          <section className="space-y-3" aria-labelledby="template-file-label">
            <div>
              <h2 id="template-file-label" className="text-sm font-medium">
                {t.office.powerpointFile}
              </h2>
              <p className="text-muted-foreground mt-1 text-xs">
                {t.office.fileLimit}
              </p>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              className="sr-only"
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              disabled={importTemplate.isPending}
            />
            {file ? (
              <div className="flex min-w-0 items-center gap-3 rounded-md border px-3 py-3">
                <span className="bg-muted flex size-10 shrink-0 items-center justify-center rounded-md">
                  <PresentationIcon className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium" title={file.name}>
                    {file.name}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {readableBytes(file.size)}
                  </p>
                </div>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  disabled={importTemplate.isPending}
                  title={t.office.removeFile}
                  aria-label={t.office.removeFile}
                >
                  <XIcon />
                </Button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={importTemplate.isPending}
                className="border-input hover:bg-muted/35 focus-visible:ring-ring flex min-h-36 w-full flex-col items-center justify-center gap-2 rounded-md border border-dashed px-5 py-6 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
              >
                <FileUpIcon className="text-muted-foreground size-7" />
                <span className="font-medium">{t.office.selectPptx}</span>
              </button>
            )}
          </section>

          <section className="space-y-2">
            <label htmlFor="template-name" className="text-sm font-medium">
              {t.office.templateName}
            </label>
            <Input
              id="template-name"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t.office.templateNamePlaceholder}
              maxLength={200}
              disabled={importTemplate.isPending}
            />
          </section>

          {validationError && (
            <Alert variant="destructive">
              <AlertDescription>{validationError}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col-reverse gap-2 border-t pt-5 sm:flex-row sm:justify-end">
            <Button variant="outline" asChild>
              <Link href="/workspace/office/templates">{t.common.cancel}</Link>
            </Button>
            <Button type="submit" disabled={!file || importTemplate.isPending}>
              {importTemplate.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <FileUpIcon />
              )}
              {importTemplate.isPending ? t.office.importing : t.common.import}
            </Button>
          </div>
        </form>
      </main>
    </div>
  );
}

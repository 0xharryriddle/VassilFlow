"use client";

import {
  ArrowLeftIcon,
  FileImageIcon,
  FilePlus2Icon,
  FileWarningIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  PresentationIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/core/i18n/hooks";
import {
  type OfficeTemplateBindingDraft,
  type OfficeTemplateSlot,
  useInstantiateOfficeTemplate,
  useOfficeTemplate,
  useOfficeTemplateVersion,
} from "@/core/office";

const MAX_IMAGE_BYTES = 12 * 1024 * 1024;

type BindingValue = string | File | null;

function UseTemplateLoading() {
  return (
    <div className="flex size-full flex-col">
      <div className="flex h-16 items-center gap-3 border-b px-4 sm:px-6">
        <Skeleton className="size-8 rounded-md" />
        <Skeleton className="h-5 w-52" />
      </div>
      <div className="mx-auto grid w-full max-w-5xl gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  );
}

function SlotField({
  slot,
  value,
  disabled,
  onChange,
}: {
  slot: OfficeTemplateSlot;
  value: BindingValue;
  disabled: boolean;
  onChange: (value: BindingValue) => void;
}) {
  const { t } = useI18n();
  const maxLength =
    slot.type === "text" ? Number(slot.constraints.max_length ?? 4000) : null;

  return (
    <div className="grid gap-3 py-4 sm:grid-cols-[minmax(150px,0.7fr)_minmax(0,1.3fr)]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor={`binding-${slot.key}`}
            className="text-sm font-medium"
          >
            {slot.label}
          </label>
          <Badge variant="outline" className="rounded-md">
            {slot.type === "text" ? t.office.textSlot : t.office.pictureSlot}
          </Badge>
          {slot.required && (
            <Badge variant="secondary" className="rounded-md">
              {t.office.required}
            </Badge>
          )}
        </div>
        <p className="text-muted-foreground mt-1 font-mono text-[11px]">
          {slot.key}
        </p>
      </div>

      {slot.type === "text" ? (
        <div className="space-y-1.5">
          <Input
            id={`binding-${slot.key}`}
            value={typeof value === "string" ? value : ""}
            onChange={(event) => onChange(event.target.value)}
            maxLength={maxLength ?? undefined}
            required={slot.required}
            disabled={disabled}
          />
          {maxLength && (
            <p className="text-muted-foreground text-right text-[11px]">
              {(typeof value === "string" ? value.length : 0).toLocaleString()}{" "}
              / {maxLength.toLocaleString()}
            </p>
          )}
        </div>
      ) : (
        <div className="min-w-0">
          <input
            id={`binding-${slot.key}`}
            type="file"
            accept="image/png,image/jpeg"
            className="sr-only"
            disabled={disabled}
            onChange={(event) => onChange(event.target.files?.[0] ?? null)}
          />
          {value instanceof File ? (
            <div className="flex min-w-0 items-center gap-3 rounded-md border px-3 py-2.5">
              <FileImageIcon className="text-muted-foreground size-5 shrink-0" />
              <span
                className="min-w-0 flex-1 truncate text-sm"
                title={value.name}
              >
                {value.name}
              </span>
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                onClick={() => onChange(null)}
                disabled={disabled}
                title={t.office.removeImage}
                aria-label={t.office.removeImage}
              >
                <XIcon />
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-start gap-1.5">
              <Button type="button" variant="outline" asChild>
                <label htmlFor={`binding-${slot.key}`}>
                  <FileImageIcon />
                  {t.office.chooseImage}
                </label>
              </Button>
              <span className="text-muted-foreground text-[11px]">
                {t.office.pngJpegLimit}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function OfficeTemplateUse() {
  const { template_id: templateId } = useParams<{ template_id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();
  const templateQuery = useOfficeTemplate(templateId);
  const requestedVersion = Number(searchParams.get("version"));
  const template = templateQuery.data;
  const versionNumber =
    Number.isInteger(requestedVersion) && requestedVersion > 0
      ? requestedVersion
      : (template?.published_versions.at(-1) ?? null);
  const versionQuery = useOfficeTemplateVersion(templateId, versionNumber);
  const version = versionQuery.data;
  const instantiateTemplate = useInstantiateOfficeTemplate();
  const [title, setTitle] = useState("");
  const [values, setValues] = useState<Record<string, BindingValue>>({});
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!template || !version) return;
    setTitle(template.title);
    setValues(
      Object.fromEntries(version.slots.map((slot) => [slot.key, null])),
    );
  }, [template, version]);

  const missingRequired = useMemo(
    () =>
      version?.slots.some((slot) => {
        if (!slot.required) return false;
        const value = values[slot.key];
        return typeof value === "string" ? !value : !(value instanceof File);
      }) ?? true,
    [values, version?.slots],
  );

  if (templateQuery.isLoading || (versionNumber && versionQuery.isLoading)) {
    return <UseTemplateLoading />;
  }
  if (
    templateQuery.isError ||
    versionQuery.isError ||
    !template ||
    !version ||
    version.status !== "published"
  ) {
    return (
      <div className="flex size-full flex-col">
        <header className="flex h-16 items-center gap-2 border-b px-4 sm:px-6">
          <SidebarTrigger className="md:hidden" />
          <Button variant="ghost" asChild>
            <Link href={`/workspace/office/templates/${templateId}`}>
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
            <EmptyTitle>{t.office.publishedVersionRequired}</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button asChild variant="outline">
              <Link href={`/workspace/office/templates/${templateId}`}>
                {t.office.backToTemplates}
              </Link>
            </Button>
          </EmptyContent>
        </Empty>
      </div>
    );
  }
  const publishedVersion = version;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    if (missingRequired) {
      setValidationError(t.office.requiredFieldMissing);
      return;
    }
    const bindings: OfficeTemplateBindingDraft[] = [];
    for (const slot of publishedVersion.slots) {
      const value = values[slot.key];
      if (slot.type === "text" && typeof value === "string" && value) {
        bindings.push({ key: slot.key, type: "text", value });
      } else if (slot.type === "picture" && value instanceof File) {
        if (
          !["image/png", "image/jpeg"].includes(value.type) ||
          value.size > MAX_IMAGE_BYTES
        ) {
          setValidationError(t.office.invalidTemplateImage);
          return;
        }
        bindings.push({ key: slot.key, type: "picture", file: value });
      }
    }
    try {
      const project = await instantiateTemplate.mutateAsync({
        templateId,
        version: publishedVersion.version,
        bindings,
        title: title.trim() ? title.trim() : undefined,
      });
      toast.success(t.office.projectCreated);
      router.push(project.project_url);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.office.templateActionFailed,
      );
    }
  }

  return (
    <div className="flex size-full min-w-0 flex-col overflow-hidden">
      <header className="flex min-h-16 shrink-0 items-center gap-2 border-b px-3 py-2 sm:px-5">
        <SidebarTrigger className="md:hidden" />
        <Button
          size="icon-sm"
          variant="ghost"
          asChild
          title={t.office.backToTemplates}
        >
          <Link
            href={`/workspace/office/templates/${templateId}`}
            aria-label={t.office.backToTemplates}
          >
            <ArrowLeftIcon />
          </Link>
        </Button>
        <PresentationIcon className="text-muted-foreground size-5 shrink-0" />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold sm:text-base">
            {t.office.useTemplateTitle(template.title)}
          </h1>
          <p className="text-muted-foreground text-xs">
            {t.office.version(version.version)}
          </p>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <form
          onSubmit={(event) => void submit(event)}
          className="mx-auto grid w-full max-w-5xl gap-7 lg:grid-cols-[minmax(0,1fr)_300px]"
        >
          <div className="min-w-0">
            <section className="space-y-2 border-b pb-5">
              <label htmlFor="project-name" className="text-sm font-medium">
                {t.office.projectName}
              </label>
              <Input
                id="project-name"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={200}
                placeholder={t.office.projectNamePlaceholder}
                disabled={instantiateTemplate.isPending}
              />
            </section>

            <section aria-labelledby="template-fields-heading">
              <div className="border-b py-5">
                <h2
                  id="template-fields-heading"
                  className="text-sm font-semibold"
                >
                  {t.office.templateFields}
                </h2>
                <p className="text-muted-foreground mt-1 text-xs">
                  {t.office.slots(version.slots.length)}
                </p>
              </div>
              <div className="divide-y">
                {version.slots.map((slot) => (
                  <SlotField
                    key={slot.key}
                    slot={slot}
                    value={values[slot.key] ?? null}
                    disabled={instantiateTemplate.isPending}
                    onChange={(value) =>
                      setValues((current) => ({
                        ...current,
                        [slot.key]: value,
                      }))
                    }
                  />
                ))}
              </div>
            </section>

            {validationError && (
              <Alert variant="destructive" className="mt-4">
                <AlertDescription>{validationError}</AlertDescription>
              </Alert>
            )}
          </div>

          <aside className="min-w-0 lg:border-l lg:pl-6">
            <section className="space-y-4 lg:sticky lg:top-5">
              <div className="flex items-start gap-2 border-b pb-4">
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
              <dl className="divide-y text-sm">
                <div className="flex justify-between gap-3 py-2">
                  <dt className="text-muted-foreground">
                    {t.office.templateName}
                  </dt>
                  <dd className="max-w-[60%] text-right font-medium">
                    {template.title}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 py-2">
                  <dt className="text-muted-foreground">{t.common.version}</dt>
                  <dd className="font-medium">{version.version}</dd>
                </div>
                <div className="flex justify-between gap-3 py-2">
                  <dt className="text-muted-foreground">
                    {t.office.visualReview}
                  </dt>
                  <dd className="font-medium">{t.office.reviewed}</dd>
                </div>
              </dl>
              <Button
                type="submit"
                className="w-full"
                disabled={missingRequired || instantiateTemplate.isPending}
              >
                {instantiateTemplate.isPending ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <FilePlus2Icon />
                )}
                {instantiateTemplate.isPending
                  ? t.office.creatingProject
                  : t.office.createProject}
              </Button>
            </section>
          </aside>
        </form>
      </main>
    </div>
  );
}

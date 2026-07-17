import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  compareOfficeRevision,
  getOfficeProject,
  getOfficePptxSelectionSurface,
  getOfficeRevision,
  getOfficeTemplate,
  getOfficeTemplateVersion,
  importOfficeTemplate,
  instantiateOfficeTemplate,
  listOfficeProjects,
  listOfficeRevisions,
  listOfficeTemplates,
  publishOfficeTemplate,
  renderOfficeProjectRevision,
  renderOfficeTemplate,
  reviewOfficeTemplateRender,
  reviewOfficeProjectRevision,
  restoreOfficeProjectRevision,
  selectOfficeProjectFinal,
  updateOfficeTemplateSlots,
} from "./api";
import type {
  OfficeProjectReviewStatus,
  OfficeTemplateBindingDraft,
  OfficeTemplateSlotDraft,
} from "./types";

export function useOfficeProjects(limit = 100) {
  return useQuery({
    queryKey: ["office", "projects", limit],
    queryFn: () => listOfficeProjects(limit),
  });
}

export function useOfficeProject(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["office", "projects", projectId],
    queryFn: () => getOfficeProject(projectId!),
    enabled: !!projectId,
  });
}

export function useOfficeRevisions(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["office", "projects", projectId, "revisions"],
    queryFn: () => listOfficeRevisions(projectId!),
    enabled: !!projectId,
  });
}

export function useOfficeRevision(
  projectId: string | null | undefined,
  revisionId: string | null | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ["office", "projects", projectId, "revisions", revisionId],
    queryFn: () => getOfficeRevision(projectId!, revisionId!),
    enabled: enabled && !!projectId && !!revisionId,
  });
}

export function useOfficePptxSelectionSurface(
  projectId: string | null | undefined,
  revisionId: string | null | undefined,
  slide: number | null | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "office",
      "projects",
      projectId,
      "revisions",
      revisionId,
      "selection",
      slide,
    ],
    queryFn: () =>
      getOfficePptxSelectionSurface(projectId!, revisionId!, slide!),
    enabled: enabled && !!projectId && !!revisionId && !!slide,
  });
}

export function useOfficeRevisionComparison(
  projectId: string | null | undefined,
  revisionId: string | null | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: [
      "office",
      "projects",
      projectId,
      "revisions",
      revisionId,
      "comparison",
    ],
    queryFn: () => compareOfficeRevision(projectId!, revisionId!),
    enabled: enabled && !!projectId && !!revisionId,
  });
}

function useInvalidateOfficeProjects() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: ["office", "projects"] });
}

export function useRenderOfficeProjectRevision() {
  const invalidate = useInvalidateOfficeProjects();
  return useMutation({
    mutationFn: ({
      projectId,
      revisionId,
    }: {
      projectId: string;
      revisionId: string;
    }) => renderOfficeProjectRevision(projectId, revisionId),
    onSuccess: () => void invalidate(),
  });
}

export function useReviewOfficeProjectRevision() {
  const invalidate = useInvalidateOfficeProjects();
  return useMutation({
    mutationFn: ({
      projectId,
      revisionId,
      evidenceIds,
      status,
      note,
    }: {
      projectId: string;
      revisionId: string;
      evidenceIds: string[];
      status: OfficeProjectReviewStatus;
      note?: string;
    }) =>
      reviewOfficeProjectRevision(
        projectId,
        revisionId,
        evidenceIds,
        status,
        note,
      ),
    onSuccess: () => void invalidate(),
  });
}

export function useSelectOfficeProjectFinal() {
  const invalidate = useInvalidateOfficeProjects();
  return useMutation({
    mutationFn: ({
      projectId,
      revisionId,
      reviewId,
      expectedCurrentRevisionId,
    }: {
      projectId: string;
      revisionId: string;
      reviewId: string;
      expectedCurrentRevisionId: string;
    }) =>
      selectOfficeProjectFinal(
        projectId,
        revisionId,
        reviewId,
        expectedCurrentRevisionId,
      ),
    onSuccess: () => void invalidate(),
  });
}

export function useRestoreOfficeProjectRevision() {
  const invalidate = useInvalidateOfficeProjects();
  return useMutation({
    mutationFn: ({
      projectId,
      targetRevisionId,
      expectedCurrentRevisionId,
    }: {
      projectId: string;
      targetRevisionId: string;
      expectedCurrentRevisionId: string;
    }) =>
      restoreOfficeProjectRevision(
        projectId,
        targetRevisionId,
        expectedCurrentRevisionId,
      ),
    onSuccess: () => void invalidate(),
  });
}

export function useOfficeTemplates(limit = 100) {
  return useQuery({
    queryKey: ["office", "templates", limit],
    queryFn: () => listOfficeTemplates(limit),
  });
}

export function useOfficeTemplate(templateId: string | null | undefined) {
  return useQuery({
    queryKey: ["office", "templates", templateId],
    queryFn: () => getOfficeTemplate(templateId!),
    enabled: !!templateId,
  });
}

export function useOfficeTemplateVersion(
  templateId: string | null | undefined,
  version: number | null | undefined,
) {
  return useQuery({
    queryKey: ["office", "templates", templateId, "versions", version],
    queryFn: () => getOfficeTemplateVersion(templateId!, version!),
    enabled: !!templateId && !!version,
  });
}

function useInvalidateOfficeTemplates() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: ["office", "templates"] });
}

export function useImportOfficeTemplate() {
  const invalidate = useInvalidateOfficeTemplates();
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) =>
      importOfficeTemplate(file, title),
    onSuccess: () => void invalidate(),
  });
}

export function useUpdateOfficeTemplateSlots() {
  const invalidate = useInvalidateOfficeTemplates();
  return useMutation({
    mutationFn: ({
      templateId,
      version,
      slots,
    }: {
      templateId: string;
      version: number;
      slots: OfficeTemplateSlotDraft[];
    }) => updateOfficeTemplateSlots(templateId, version, slots),
    onSuccess: () => void invalidate(),
  });
}

export function useRenderOfficeTemplate() {
  const invalidate = useInvalidateOfficeTemplates();
  return useMutation({
    mutationFn: ({
      templateId,
      version,
    }: {
      templateId: string;
      version: number;
    }) => renderOfficeTemplate(templateId, version),
    onSuccess: () => void invalidate(),
  });
}

export function useReviewOfficeTemplateRender() {
  const invalidate = useInvalidateOfficeTemplates();
  return useMutation({
    mutationFn: ({
      templateId,
      version,
      evidenceId,
      status,
      note,
    }: {
      templateId: string;
      version: number;
      evidenceId: string;
      status: "reviewed" | "external_review_required";
      note?: string;
    }) =>
      reviewOfficeTemplateRender(templateId, version, evidenceId, status, note),
    onSuccess: () => void invalidate(),
  });
}

export function usePublishOfficeTemplate() {
  const invalidate = useInvalidateOfficeTemplates();
  return useMutation({
    mutationFn: ({
      templateId,
      version,
    }: {
      templateId: string;
      version: number;
    }) => publishOfficeTemplate(templateId, version),
    onSuccess: () => void invalidate(),
  });
}

export function useInstantiateOfficeTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      templateId,
      version,
      bindings,
      title,
    }: {
      templateId: string;
      version: number;
      bindings: OfficeTemplateBindingDraft[];
      title?: string;
    }) => instantiateOfficeTemplate(templateId, version, bindings, title),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["office", "projects"] }),
  });
}

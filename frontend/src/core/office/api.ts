import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  OfficeFinalSelection,
  OfficeProjectDetail,
  OfficeProjectReview,
  OfficeProjectReviewStatus,
  OfficeProjectsResponse,
  OfficePptxSelectionSurface,
  OfficeRenderSet,
  OfficeRevisionDetail,
  OfficeRevisionComparison,
  OfficeRevisionsResponse,
  OfficeRestoreResult,
  OfficeTemplateDetail,
  OfficeTemplateBindingDraft,
  OfficeTemplateInstantiation,
  OfficeTemplatesResponse,
  OfficeTemplateSlotDraft,
  OfficeTemplateVersionDetail,
} from "./types";

function officeApiURL(path: string): string {
  return `${getBackendBaseURL()}${path}`;
}

async function readJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? `${message}: ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function listOfficeProjects(
  limit = 100,
): Promise<OfficeProjectsResponse> {
  const response = await fetch(
    officeApiURL(`/api/office/projects?limit=${encodeURIComponent(limit)}`),
  );
  return readJson(response, "Failed to load Office projects");
}

export async function getOfficeProject(
  projectId: string,
): Promise<OfficeProjectDetail> {
  const response = await fetch(
    officeApiURL(`/api/office/projects/${encodeURIComponent(projectId)}`),
  );
  return readJson(response, "Failed to load Office project");
}

export async function listOfficeRevisions(
  projectId: string,
  limit = 100,
): Promise<OfficeRevisionsResponse> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions?limit=${encodeURIComponent(limit)}`,
    ),
  );
  return readJson(response, "Failed to load Office revisions");
}

export async function getOfficeRevision(
  projectId: string,
  revisionId: string,
): Promise<OfficeRevisionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}`,
    ),
  );
  return readJson(response, "Failed to load Office revision");
}

export async function getOfficePptxSelectionSurface(
  projectId: string,
  revisionId: string,
  slide: number,
): Promise<OfficePptxSelectionSurface> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/selection?slide=${encodeURIComponent(slide)}`,
    ),
  );
  return readJson(response, "Failed to load PowerPoint objects");
}

export async function compareOfficeRevision(
  projectId: string,
  revisionId: string,
): Promise<OfficeRevisionComparison> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/comparison`,
    ),
  );
  return readJson(response, "Failed to compare Office revision");
}

export async function renderOfficeProjectRevision(
  projectId: string,
  revisionId: string,
): Promise<OfficeRenderSet> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/render`,
    ),
    { method: "POST" },
  );
  return readJson(response, "Failed to render Office revision");
}

export async function reviewOfficeProjectRevision(
  projectId: string,
  revisionId: string,
  evidenceIds: string[],
  status: OfficeProjectReviewStatus,
  note?: string,
): Promise<OfficeProjectReview> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/reviews`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        evidence_ids: evidenceIds,
        ...(note?.trim() ? { note: note.trim() } : {}),
      }),
    },
  );
  return readJson(response, "Failed to review Office revision");
}

export async function selectOfficeProjectFinal(
  projectId: string,
  revisionId: string,
  reviewId: string,
  expectedCurrentRevisionId: string,
): Promise<OfficeFinalSelection> {
  const response = await fetch(
    officeApiURL(`/api/office/projects/${encodeURIComponent(projectId)}/final`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision_id: revisionId,
        review_id: reviewId,
        expected_current_revision_id: expectedCurrentRevisionId,
      }),
    },
  );
  return readJson(response, "Failed to select final Office artifact");
}

export async function restoreOfficeProjectRevision(
  projectId: string,
  targetRevisionId: string,
  expectedCurrentRevisionId: string,
): Promise<OfficeRestoreResult> {
  const response = await fetch(
    officeApiURL(
      `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(targetRevisionId)}/restore`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_current_revision_id: expectedCurrentRevisionId,
      }),
    },
  );
  return readJson(response, "Failed to restore Office revision");
}

export async function listOfficeTemplates(
  limit = 100,
): Promise<OfficeTemplatesResponse> {
  const response = await fetch(
    officeApiURL(`/api/office/templates?limit=${encodeURIComponent(limit)}`),
  );
  return readJson(response, "Failed to load Office templates");
}

export async function importOfficeTemplate(
  file: File,
  title?: string,
): Promise<OfficeTemplateDetail> {
  const form = new FormData();
  form.append("file", file);
  if (title?.trim()) form.append("title", title.trim());
  const response = await fetch(officeApiURL("/api/office/templates"), {
    method: "POST",
    body: form,
  });
  return readJson(response, "Failed to import Office template");
}

export async function getOfficeTemplate(
  templateId: string,
): Promise<OfficeTemplateDetail> {
  const response = await fetch(
    officeApiURL(`/api/office/templates/${encodeURIComponent(templateId)}`),
  );
  return readJson(response, "Failed to load Office template");
}

export async function getOfficeTemplateVersion(
  templateId: string,
  version: number,
): Promise<OfficeTemplateVersionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}`,
    ),
  );
  return readJson(response, "Failed to load Office template version");
}

export async function updateOfficeTemplateSlots(
  templateId: string,
  version: number,
  slots: OfficeTemplateSlotDraft[],
): Promise<OfficeTemplateVersionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/slots`,
    ),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slots }),
    },
  );
  return readJson(response, "Failed to update Office template slots");
}

export async function renderOfficeTemplate(
  templateId: string,
  version: number,
): Promise<OfficeTemplateVersionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/render`,
    ),
    { method: "POST" },
  );
  return readJson(response, "Failed to render Office template");
}

export async function reviewOfficeTemplateRender(
  templateId: string,
  version: number,
  evidenceId: string,
  status: "reviewed" | "external_review_required",
  note?: string,
): Promise<OfficeTemplateVersionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/renders/${encodeURIComponent(evidenceId)}/review`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, ...(note ? { note } : {}) }),
    },
  );
  return readJson(response, "Failed to review Office template render");
}

export async function publishOfficeTemplate(
  templateId: string,
  version: number,
): Promise<OfficeTemplateVersionDetail> {
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/publish`,
    ),
    { method: "POST" },
  );
  return readJson(response, "Failed to publish Office template");
}

export async function instantiateOfficeTemplate(
  templateId: string,
  version: number,
  bindings: OfficeTemplateBindingDraft[],
  title?: string,
): Promise<OfficeTemplateInstantiation> {
  const form = new FormData();
  const files: File[] = [];
  const payload = bindings.map((binding) => {
    if (binding.type === "text") return binding;
    const uploadIndex = files.push(binding.file) - 1;
    return {
      key: binding.key,
      type: binding.type,
      upload_index: uploadIndex,
    };
  });
  form.append("bindings_json", JSON.stringify({ bindings: payload }));
  if (title?.trim()) form.append("title", title.trim());
  for (const file of files) form.append("files", file);
  const response = await fetch(
    officeApiURL(
      `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/instantiate`,
    ),
    { method: "POST", body: form },
  );
  return readJson(response, "Failed to create Office project from template");
}

export function officeTemplateSourceURL(
  templateId: string,
  version: number,
): string {
  return officeApiURL(
    `/api/office/templates/${encodeURIComponent(templateId)}/versions/${encodeURIComponent(version)}/source`,
  );
}

export function officeResourceURL(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return officeApiURL(path.startsWith("/") ? path : `/${path}`);
}

export function officeArtifactURL(
  projectId: string,
  revisionId: string,
): string {
  return officeApiURL(
    `/api/office/projects/${encodeURIComponent(projectId)}/revisions/${encodeURIComponent(revisionId)}/artifact`,
  );
}

export function officeFinalArtifactURL(projectId: string): string {
  return officeApiURL(
    `/api/office/projects/${encodeURIComponent(projectId)}/final/artifact`,
  );
}

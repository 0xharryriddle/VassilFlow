import type {
  OfficePptxObjectSelectionRequest,
  OfficePptxSelectionObject,
  OfficePptxSelectionSurface,
} from "./types";

const PROJECT_ID_PATTERN = /^ofp_[0-9a-f]{32}$/;
const REVISION_ID_PATTERN = /^ofr_[0-9a-f]{32}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const OBJECT_PATH_PATTERN = /^\/slide\[[1-9]\d*\]\/.+/;

export function buildOfficeObjectSelectionRequest(
  surface: OfficePptxSelectionSurface,
  object: OfficePptxSelectionObject,
): OfficePptxObjectSelectionRequest {
  return {
    kind: "pptx_object",
    project_id: surface.project_id,
    revision_id: surface.revision_id,
    source_sha256: surface.source_sha256,
    slide_index: surface.slide.index,
    object_path: object.path,
    object_fingerprint: object.object_fingerprint,
  };
}

export function officeSelectionSearchParams(
  request: OfficePptxObjectSelectionRequest,
): URLSearchParams {
  const params = new URLSearchParams();
  params.set("office_project_id", request.project_id);
  params.set("office_revision_id", request.revision_id);
  params.set("office_source_sha256", request.source_sha256);
  params.set("office_slide", String(request.slide_index));
  params.set("office_object_path", request.object_path);
  params.set("office_object_fingerprint", request.object_fingerprint);
  return params;
}

export function buildOfficeSelectionChatHref(
  request: OfficePptxObjectSelectionRequest,
): string {
  const params = officeSelectionSearchParams(request);
  params.set("starter", "edit-selection");
  return `/workspace/agents/office/chats/new?${params.toString()}`;
}

export function parseOfficeSelectionSearchParams(
  searchParams: Pick<URLSearchParams, "get">,
): OfficePptxObjectSelectionRequest | null {
  const projectId = searchParams.get("office_project_id");
  const revisionId = searchParams.get("office_revision_id");
  const sourceSha256 = searchParams.get("office_source_sha256");
  const slideText = searchParams.get("office_slide");
  const objectPath = searchParams.get("office_object_path");
  const objectFingerprint = searchParams.get("office_object_fingerprint");
  if (
    !projectId ||
    !revisionId ||
    !sourceSha256 ||
    !slideText ||
    !objectPath ||
    !objectFingerprint
  ) {
    return null;
  }
  const slideIndex = Number(slideText);
  if (
    !PROJECT_ID_PATTERN.test(projectId) ||
    !REVISION_ID_PATTERN.test(revisionId) ||
    !SHA256_PATTERN.test(sourceSha256) ||
    !Number.isSafeInteger(slideIndex) ||
    slideIndex < 1 ||
    slideIndex > 10_000 ||
    objectPath.length > 1_024 ||
    !OBJECT_PATH_PATTERN.test(objectPath) ||
    !SHA256_PATTERN.test(objectFingerprint)
  ) {
    return null;
  }
  return {
    kind: "pptx_object",
    project_id: projectId,
    revision_id: revisionId,
    source_sha256: sourceSha256,
    slide_index: slideIndex,
    object_path: objectPath,
    object_fingerprint: objectFingerprint,
  };
}

export function resolveOfficeSelectionObject(
  surface: OfficePptxSelectionSurface | undefined,
  request: OfficePptxObjectSelectionRequest | null,
): OfficePptxSelectionObject | null {
  if (
    !request ||
    surface?.project_id !== request.project_id ||
    surface?.revision_id !== request.revision_id ||
    surface?.source_sha256 !== request.source_sha256 ||
    surface?.slide.index !== request.slide_index
  ) {
    return null;
  }
  return (
    surface.objects.find(
      (object) =>
        object.selection_status === "selectable" &&
        object.path === request.object_path &&
        object.object_fingerprint === request.object_fingerprint,
    ) ?? null
  );
}

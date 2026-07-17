export type OfficeFormat = "docx" | "pptx" | "xlsx";

export type OfficeArtifactIdentity = {
  sha256: string;
  size_bytes: number;
};

export type OfficePreviewPage = {
  page: number;
  source_slide: number | null;
  width: number;
  height: number;
  sha256: string;
  url: string;
};

export type OfficePptxSelectionOperation =
  | "replace_pptx_text"
  | "format_pptx_runs"
  | "format_pptx_paragraphs"
  | "format_pptx_shapes"
  | "format_pptx_lines"
  | "replace_pptx_picture_sources";

export type OfficePptxSelectionOverlay = {
  left_percent: number;
  top_percent: number;
  width_percent: number;
  height_percent: number;
  rotation_degrees: number | null;
};

export type OfficePptxSelectionObject = {
  path: string;
  parent_path: string;
  kind: string;
  name: string | null;
  z_order: number | null;
  identity_source: string;
  selection_status: "selectable" | "unsupported_kind" | "unstable_identity";
  allowed_operations: OfficePptxSelectionOperation[];
  geometry: Record<string, unknown>;
  overlay: OfficePptxSelectionOverlay | null;
  text_preview: string;
  text_truncated: boolean;
  object_fingerprint: string;
};

export type OfficePptxSelectionSurface = {
  schema: string;
  format: "pptx";
  project_id: string;
  revision_id: string;
  is_current: boolean;
  source_sha256: string;
  slide: {
    index: number;
    path: string;
    title: string | null;
    width_emu: number;
    height_emu: number;
  };
  object_count: number;
  objects_returned: number;
  objects_truncated: boolean;
  objects: OfficePptxSelectionObject[];
};

export type OfficePptxObjectSelectionRequest = {
  kind: "pptx_object";
  project_id: string;
  revision_id: string;
  source_sha256: string;
  slide_index: number;
  object_path: string;
  object_fingerprint: string;
};

export type OfficeRenderEvidence = {
  evidence_id: string;
  revision_id: string;
  created_at: string;
  source_sha256: string;
  page_count: number;
  rendered_page_count: number;
  start_page: number;
  end_page: number;
  has_more: boolean;
  visual_review_status: string;
  renderer: string;
  renderer_version: string;
  pipeline_fingerprint: string;
  preview_pages: OfficePreviewPage[];
};

export type OfficeRevisionQuality = {
  package_validation_status: string;
  preflight_status: string;
  render_evidence_status: string;
  visual_review_status: string;
};

export type OfficeProjectReviewStatus = "approved" | "changes_requested";

export type OfficeProjectReview = {
  review_id: string;
  revision_id: string;
  created_at: string;
  status: OfficeProjectReviewStatus;
  note: string | null;
  evidence_ids: string[];
  page_count: number;
  render_set_sha256: string;
};

export type OfficeFinalSelection = {
  selection_id: string;
  revision_id: string;
  review_id: string;
  created_at: string;
  artifact: OfficeArtifactIdentity;
};

export type OfficeRenderSet = {
  complete: boolean;
  page_count: number;
  rendered_page_count: number;
  evidence_ids: string[];
  evidence: OfficeRenderEvidence[];
};

export type OfficeSemanticDelta = {
  path: string;
  semantic_kind: string;
  property: string;
  before: unknown;
  after: unknown;
};

export type OfficeChangeReceipt = {
  schema: string;
  format: OfficeFormat;
  status: "changed" | "unchanged";
  source: OfficeArtifactIdentity;
  result: OfficeArtifactIdentity;
  operation_count: number;
  applied_operation_ids: string[];
  operations: Array<{
    operation_id: string;
    position: number;
    type: string;
    match_count: number;
    target_path_count: number;
    target_paths: string[];
  }>;
  semantic_changes: {
    coverage: "complete" | "partial";
    evaluated_target_count: number;
    changed_target_count: number;
    changed_target_paths: string[];
    semantic_delta_count: number;
    semantic_deltas: OfficeSemanticDelta[];
  };
  package_changes: {
    part_change_count: number;
    parts: Array<Record<string, unknown>>;
    relationship_change_count: number;
    relationships: Array<Record<string, unknown>>;
  };
};

export type OfficeGenerationObject = {
  slide_id: string;
  element_id: string;
  element_kind: string;
  role: string;
  object_path: string;
  object_kind: string;
  authored_name: string;
};

export type OfficeGenerationSlide = {
  slide_id: string;
  slide_index: number;
  slide_path: string;
  layout: string;
  purpose: string;
  object_count: number;
  objects: OfficeGenerationObject[];
};

export type OfficeGenerationReceipt = {
  schema: string;
  compiler: {
    id: string;
    version: number;
  };
  intent: {
    schema: string;
    sha256: string;
    size_bytes: number;
  };
  output: OfficeArtifactIdentity;
  presentation: {
    title: string;
    aspect_ratio: string;
    slide_width_emu: number;
    slide_height_emu: number;
    slide_count: number;
    object_count: number;
    mapping_sha256: string;
  };
  slides: OfficeGenerationSlide[];
  assets: Array<{
    element_id: string;
    sha256: string;
    size_bytes: number;
    format: string;
    width_px: number;
    height_px: number;
    alt_text_sha256: string;
  }>;
  bounds: {
    slides_returned: number;
    slides_truncated: boolean;
    objects_returned: number;
    objects_truncated: boolean;
    assets_returned: number;
    assets_truncated: boolean;
  };
};

export type OfficeGenerationPreflight = {
  schema: string;
  source_sha256: string;
  source_size_bytes: number;
  slide_count: number;
  object_count: number;
  picture_count: number;
  finding_count: number;
  findings_returned: number;
  findings_truncated: boolean;
  findings_by_severity: Record<string, number>;
};

export type OfficeRevisionSummary = {
  revision_id: string;
  parent_revision_id: string | null;
  sequence: number;
  kind: "baseline" | "generation" | "edit" | "restore";
  created_at: string;
  artifact: OfficeArtifactIdentity;
  operation_count: number;
  changed_target_count: number;
  part_change_count: number;
  relationship_change_count: number;
  generation_slide_count: number;
  generation_object_count: number;
  quality: OfficeRevisionQuality;
  latest_render: OfficeRenderEvidence | null;
  restored_from_revision_id: string | null;
  latest_review: OfficeProjectReview | null;
  is_final: boolean;
};

export type OfficeProjectSummary = {
  project_id: string;
  title: string;
  format: OfficeFormat;
  created_at: string;
  updated_at: string;
  primary_thread_id: string | null;
  revision_count: number;
  template: {
    template_id: string;
    version: number;
    source_sha256: string;
  } | null;
  final_selection: OfficeFinalSelection | null;
  current_revision: OfficeRevisionSummary;
};

export type OfficeProjectDetail = OfficeProjectSummary & {
  render_evidence: OfficeRenderEvidence[];
  render_set: OfficeRenderSet;
  generation_receipt: OfficeGenerationReceipt | null;
  generation_preflight: OfficeGenerationPreflight | null;
};

export type OfficeProjectsResponse = {
  projects: OfficeProjectSummary[];
};

export type OfficeRevisionsResponse = {
  project_id: string;
  revisions: OfficeRevisionSummary[];
};

export type OfficeRevisionDetail = {
  project_id: string;
  title: string;
  format: OfficeFormat;
  is_current: boolean;
  revision: OfficeRevisionSummary;
  render_evidence: OfficeRenderEvidence[];
  render_set: OfficeRenderSet;
  operation_receipt: OfficeChangeReceipt | null;
  generation_receipt: OfficeGenerationReceipt | null;
  generation_preflight: OfficeGenerationPreflight | null;
};

export type OfficeRevisionComparison = {
  project_id: string;
  format: OfficeFormat;
  base_revision: OfficeRevisionSummary;
  revision: OfficeRevisionSummary;
  operation_receipt: OfficeChangeReceipt;
  before_render: OfficeRenderSet;
  after_render: OfficeRenderSet;
};

export type OfficeRestoreResult = {
  project_id: string;
  revision_id: string;
  parent_revision_id: string;
  restored_from_revision_id: string;
  sequence: number;
  artifact: OfficeArtifactIdentity;
  project_url: string;
};

export type OfficeTemplateStatus = "draft" | "published";
export type OfficeTemplateSlotType = "text" | "picture";

export type OfficeTemplateRender = {
  status: "not_recorded" | "available";
  evidence_id: string | null;
  created_at: string | null;
  source_sha256: string | null;
  page_count: number;
  rendered_page_count: number;
  pipeline_fingerprint: string | null;
  renderer: string | null;
  renderer_version: string | null;
  visual_review_status: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_note: string | null;
  preview_pages: OfficePreviewPage[];
};

export type OfficeTemplateVersionSummary = {
  template_id: string;
  version: number;
  status: OfficeTemplateStatus;
  format: "pptx";
  filename: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  source: OfficeArtifactIdentity;
  validation_status: string;
  slide_count: number;
  object_count: number;
  preflight_finding_count: number;
  preflight_findings_by_severity: Record<string, number>;
  slot_candidate_count: number;
  slot_count: number;
  render: OfficeTemplateRender;
};

export type OfficeTemplateCandidate = {
  candidate_id: string;
  source_fingerprint: string;
  type: OfficeTemplateSlotType;
  path: string;
  slide_index: number;
  default_label: string;
  selector: Record<string, unknown>;
  source: Record<string, unknown>;
};

export type OfficeTemplateSlot = {
  key: string;
  label: string;
  type: OfficeTemplateSlotType;
  required: boolean;
  candidate_id: string;
  source_fingerprint: string;
  selector: Record<string, unknown>;
  constraints: Record<string, unknown>;
  allowed_operations: string[];
};

export type OfficeTemplateVersionDetail = OfficeTemplateVersionSummary & {
  validation: Record<string, unknown>;
  locked_policy: Record<string, unknown>;
  slot_candidates: OfficeTemplateCandidate[];
  slots: OfficeTemplateSlot[];
};

export type OfficeTemplateSummary = {
  template_id: string;
  title: string;
  format: "pptx";
  owner_scope: "user";
  created_at: string;
  updated_at: string;
  latest_version: number;
  draft_version: number | null;
  published_versions: number[];
  archived: boolean;
  status: OfficeTemplateStatus;
  active_version: OfficeTemplateVersionSummary;
};

export type OfficeTemplateDetail = OfficeTemplateSummary & {
  versions: OfficeTemplateVersionSummary[];
};

export type OfficeTemplatesResponse = {
  templates: OfficeTemplateSummary[];
};

export type OfficeTemplateSlotDraft = {
  key: string;
  label: string;
  type: OfficeTemplateSlotType;
  candidate_id: string;
  required: boolean;
  max_length?: number | null;
};

export type OfficeTemplateTextBindingDraft = {
  key: string;
  type: "text";
  value: string;
};

export type OfficeTemplatePictureBindingDraft = {
  key: string;
  type: "picture";
  file: File;
};

export type OfficeTemplateBindingDraft =
  | OfficeTemplateTextBindingDraft
  | OfficeTemplatePictureBindingDraft;

export type OfficeTemplateInstantiation = {
  template_id: string;
  template_version: number;
  project_id: string;
  revision_id: string;
  baseline_revision_id: string;
  project_title: string;
  artifact: OfficeArtifactIdentity;
  bound_slot_keys: string[];
  omitted_optional_slot_keys: string[];
  operation_count: number;
  changed_target_count: number;
  preflight_finding_count: number;
  render_evidence_status: "available" | "partial" | "not_available";
  render_evidence_ids: string[];
  project_url: string;
};

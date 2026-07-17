import { expect, test, type Route } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  type MockOfficeProject,
  type MockOfficeSelectionSurface,
} from "./utils/mock-api";

const PROJECT_ID = `ofp_${"1".repeat(32)}`;
const REVISION_ID = `ofr_${"2".repeat(32)}`;
const BASELINE_ID = `ofr_${"3".repeat(32)}`;
const EVIDENCE_ID = `ofe_${"4".repeat(32)}`;
const BASELINE_EVIDENCE_ID = `ofe_${"5".repeat(32)}`;
const SHA = "a".repeat(64);
const BASELINE_SHA = "e".repeat(64);
const TITLE_OBJECT_FINGERPRINT = "6".repeat(64);
const GENERATED_PROJECT_ID = `ofp_${"7".repeat(32)}`;
const GENERATED_REVISION_ID = `ofr_${"8".repeat(32)}`;
const GENERATED_EVIDENCE_ID = `ofe_${"9".repeat(32)}`;
const GENERATED_SHA = "f".repeat(64);
const GENERATED_INTENT_SHA = "1".repeat(64);

const renderEvidence = {
  evidence_id: EVIDENCE_ID,
  revision_id: REVISION_ID,
  created_at: "2026-07-16T09:35:00Z",
  source_sha256: SHA,
  page_count: 2,
  rendered_page_count: 2,
  start_page: 1,
  end_page: 2,
  has_more: false,
  visual_review_status: "pending",
  renderer: "VassilFlow Office Renderer",
  renderer_version: "1.0",
  pipeline_fingerprint: "b".repeat(64),
  preview_pages: [
    {
      page: 1,
      source_slide: 1,
      width: 1600,
      height: 900,
      sha256: "c".repeat(64),
      url: `/api/office/projects/${PROJECT_ID}/renders/${EVIDENCE_ID}/pages/1`,
    },
    {
      page: 2,
      source_slide: 2,
      width: 1600,
      height: 900,
      sha256: "d".repeat(64),
      url: `/api/office/projects/${PROJECT_ID}/renders/${EVIDENCE_ID}/pages/2`,
    },
  ],
};

const baselineRenderEvidence = {
  ...renderEvidence,
  evidence_id: BASELINE_EVIDENCE_ID,
  revision_id: BASELINE_ID,
  created_at: "2026-07-16T09:25:00Z",
  source_sha256: BASELINE_SHA,
  visual_review_status: "not_performed",
  preview_pages: renderEvidence.preview_pages.map((page) => ({
    ...page,
    sha256: page.page === 1 ? "8".repeat(64) : "9".repeat(64),
    url: `/api/office/projects/${PROJECT_ID}/renders/${BASELINE_EVIDENCE_ID}/pages/${page.page}`,
  })),
};

const currentRenderSet = {
  complete: true,
  page_count: 2,
  rendered_page_count: 2,
  evidence_ids: [EVIDENCE_ID],
  evidence: [renderEvidence],
};

const baselineRenderSet = {
  complete: true,
  page_count: 2,
  rendered_page_count: 2,
  evidence_ids: [BASELINE_EVIDENCE_ID],
  evidence: [baselineRenderEvidence],
};

const operationReceipt = {
  schema: "vassilflow.office.change-receipt.v1",
  format: "pptx",
  status: "changed",
  source: { sha256: BASELINE_SHA, size_bytes: 124_000 },
  result: { sha256: SHA, size_bytes: 128_000 },
  operation_count: 2,
  applied_operation_ids: ["replace-quarter-title", "format-quarter-title"],
  operations: [
    {
      operation_id: "replace-quarter-title",
      position: 1,
      type: "replace_pptx_text",
      match_count: 1,
      target_path_count: 1,
      target_paths: ["/slide[1]/shape[@id=2]"],
    },
    {
      operation_id: "format-quarter-title",
      position: 2,
      type: "format_pptx_shape",
      match_count: 1,
      target_path_count: 1,
      target_paths: ["/slide[1]/shape[@id=2]/paragraph[1]/run[1]"],
    },
  ],
  semantic_changes: {
    coverage: "complete",
    evaluated_target_count: 2,
    changed_target_count: 2,
    changed_target_paths: [
      "/slide[1]/shape[@id=2]",
      "/slide[1]/shape[@id=2]/paragraph[1]/run[1]",
    ],
    semantic_delta_count: 2,
    semantic_deltas: [
      {
        path: "/slide[1]/shape[@id=2]",
        semantic_kind: "pptx_shape_text",
        property: "text",
        before: "Q3 company update",
        after: "Q4 company update",
      },
      {
        path: "/slide[1]/shape[@id=2]/paragraph[1]/run[1]",
        semantic_kind: "pptx_text_run",
        property: "font_size",
        before: 24,
        after: 28,
      },
    ],
  },
  package_changes: {
    part_change_count: 3,
    parts: [],
    relationship_change_count: 1,
    relationships: [],
  },
};

const currentRevision = {
  revision_id: REVISION_ID,
  parent_revision_id: BASELINE_ID,
  sequence: 2,
  kind: "edit",
  created_at: "2026-07-16T09:30:00Z",
  artifact: { sha256: SHA, size_bytes: 128_000 },
  operation_count: 2,
  changed_target_count: 2,
  part_change_count: 3,
  relationship_change_count: 1,
  quality: {
    package_validation_status: "valid",
    preflight_status: "not_recorded",
    render_evidence_status: "available",
    visual_review_status: "pending",
  },
  latest_render: renderEvidence,
  render_set: currentRenderSet,
  operation_receipt: operationReceipt,
  restored_from_revision_id: null,
  latest_review: null,
  is_final: false,
};

const baselineRevision = {
  ...currentRevision,
  revision_id: BASELINE_ID,
  parent_revision_id: null,
  sequence: 1,
  kind: "baseline",
  created_at: "2026-07-16T09:20:00Z",
  artifact: { sha256: BASELINE_SHA, size_bytes: 124_000 },
  operation_count: 0,
  changed_target_count: 0,
  part_change_count: 0,
  relationship_change_count: 0,
  quality: {
    package_validation_status: "valid",
    preflight_status: "not_recorded",
    render_evidence_status: "available",
    visual_review_status: "not_performed",
  },
  latest_render: baselineRenderEvidence,
  render_set: baselineRenderSet,
  operation_receipt: null,
};

const OFFICE_PROJECT: MockOfficeProject = {
  project_id: PROJECT_ID,
  title: "Quarterly update.pptx",
  format: "pptx",
  created_at: "2026-07-16T09:20:00Z",
  updated_at: "2026-07-16T09:35:00Z",
  primary_thread_id: MOCK_THREAD_ID,
  revision_count: 2,
  template: null,
  final_selection: null,
  current_revision: currentRevision,
  render_evidence: [renderEvidence],
  render_set: currentRenderSet,
  revisions: [currentRevision, baselineRevision],
};

const generatedRenderEvidence = {
  ...renderEvidence,
  evidence_id: GENERATED_EVIDENCE_ID,
  revision_id: GENERATED_REVISION_ID,
  source_sha256: GENERATED_SHA,
  page_count: 1,
  rendered_page_count: 1,
  end_page: 1,
  preview_pages: [
    {
      page: 1,
      source_slide: 1,
      width: 1600,
      height: 900,
      sha256: "2".repeat(64),
      url: `/api/office/projects/${GENERATED_PROJECT_ID}/renders/${GENERATED_EVIDENCE_ID}/pages/1`,
    },
  ],
};

const generatedRenderSet = {
  complete: true,
  page_count: 1,
  rendered_page_count: 1,
  evidence_ids: [GENERATED_EVIDENCE_ID],
  evidence: [generatedRenderEvidence],
};

const generationReceipt = {
  schema: "vassilflow.office.presentation_generation_receipt.v1",
  compiler: { id: "vassilflow-native-pptx", version: 1 },
  intent: {
    schema: "vassilflow.office.presentation_intent.v1",
    sha256: GENERATED_INTENT_SHA,
    size_bytes: 642,
  },
  output: { sha256: GENERATED_SHA, size_bytes: 31_500 },
  presentation: {
    title: "Native launch deck",
    aspect_ratio: "16:9",
    slide_width_emu: 12_191_999,
    slide_height_emu: 6_858_000,
    slide_count: 1,
    object_count: 2,
    mapping_sha256: "3".repeat(64),
  },
  slides: [
    {
      slide_id: "opening",
      slide_index: 1,
      slide_path: "/slide[1]",
      layout: "title",
      purpose: "Open the product launch review",
      object_count: 2,
      objects: [
        {
          slide_id: "opening",
          element_id: "opening-accent",
          element_kind: "shape",
          role: "accent_bar",
          object_path: "/slide[1]/shape[@id=2]",
          object_kind: "shape",
          authored_name: "VFGEN:opening:opening-accent",
        },
        {
          slide_id: "opening",
          element_id: "opening-title",
          element_kind: "text",
          role: "title",
          object_path: "/slide[1]/shape[@id=3]",
          object_kind: "title_placeholder",
          authored_name: "VFGEN:opening:opening-title",
        },
      ],
    },
  ],
  assets: [],
  bounds: {
    slides_returned: 1,
    slides_truncated: false,
    objects_returned: 2,
    objects_truncated: false,
    assets_returned: 0,
    assets_truncated: false,
  },
};

const generationPreflight = {
  schema: "vassilflow.office.pptx.quality_preflight.v1",
  source_sha256: GENERATED_SHA,
  source_size_bytes: 31_500,
  slide_count: 1,
  object_count: 2,
  picture_count: 0,
  finding_count: 0,
  findings_returned: 0,
  findings_truncated: false,
  findings_by_severity: {},
};

const generatedRevision = {
  revision_id: GENERATED_REVISION_ID,
  parent_revision_id: null,
  sequence: 1,
  kind: "generation",
  created_at: "2026-07-17T09:30:00Z",
  artifact: { sha256: GENERATED_SHA, size_bytes: 31_500 },
  operation_count: 0,
  changed_target_count: 0,
  part_change_count: 0,
  relationship_change_count: 0,
  generation_slide_count: 1,
  generation_object_count: 2,
  quality: {
    package_validation_status: "valid",
    preflight_status: "recorded",
    render_evidence_status: "available",
    visual_review_status: "pending",
  },
  latest_render: generatedRenderEvidence,
  render_set: generatedRenderSet,
  operation_receipt: null,
  generation_receipt: generationReceipt,
  generation_preflight: generationPreflight,
  restored_from_revision_id: null,
  latest_review: null,
  is_final: false,
};

const GENERATED_PROJECT: MockOfficeProject = {
  project_id: GENERATED_PROJECT_ID,
  title: "Native launch deck.pptx",
  format: "pptx",
  created_at: "2026-07-17T09:30:00Z",
  updated_at: "2026-07-17T09:35:00Z",
  primary_thread_id: MOCK_THREAD_ID,
  revision_count: 1,
  template: null,
  final_selection: null,
  current_revision: generatedRevision,
  render_evidence: [generatedRenderEvidence],
  render_set: generatedRenderSet,
  generation_receipt: generationReceipt,
  generation_preflight: generationPreflight,
  revisions: [generatedRevision],
};

function officeSelectionSurface({
  revisionId,
  sourceSha256,
  isCurrent,
  slide,
}: {
  revisionId: string;
  sourceSha256: string;
  isCurrent: boolean;
  slide: number;
}): MockOfficeSelectionSurface {
  const title = slide === 1 ? "Quarter title" : "Performance summary";
  const text = slide === 1 ? "Q4 company update" : "Revenue and margin";
  const fingerprint =
    slide === 1 && isCurrent
      ? TITLE_OBJECT_FINGERPRINT
      : String((slide + (isCurrent ? 1 : 3)) % 10).repeat(64);
  return {
    schema: "vassilflow.office.pptx_object_selection.v1",
    format: "pptx",
    project_id: PROJECT_ID,
    revision_id: revisionId,
    is_current: isCurrent,
    source_sha256: sourceSha256,
    slide: {
      index: slide,
      path: `/slide[${slide}]`,
      title,
      width_emu: 12_192_000,
      height_emu: 6_858_000,
    },
    object_count: 1,
    objects_returned: 1,
    objects_truncated: false,
    objects: [
      {
        path: `/slide[${slide}]/shape[@id=2]`,
        parent_path: `/slide[${slide}]`,
        kind: "text_box",
        name: title,
        z_order: 2,
        identity_source: "authored_id",
        selection_status: "selectable",
        allowed_operations: [
          "replace_pptx_text",
          "format_pptx_runs",
          "format_pptx_paragraphs",
          "format_pptx_shapes",
          "format_pptx_lines",
        ],
        geometry: {
          x_emu: 1_219_200,
          y_emu: 1_028_700,
          width_emu: 7_315_200,
          height_emu: 1_234_440,
        },
        overlay: {
          left_percent: 10,
          top_percent: 15,
          width_percent: 60,
          height_percent: 18,
          rotation_degrees: 0,
        },
        text_preview: text,
        text_truncated: false,
        object_fingerprint: fingerprint,
      },
    ],
  };
}

const OFFICE_SELECTION_SURFACES = [
  officeSelectionSurface({
    revisionId: REVISION_ID,
    sourceSha256: SHA,
    isCurrent: true,
    slide: 1,
  }),
  officeSelectionSurface({
    revisionId: REVISION_ID,
    sourceSha256: SHA,
    isCurrent: true,
    slide: 2,
  }),
  officeSelectionSurface({
    revisionId: BASELINE_ID,
    sourceSha256: BASELINE_SHA,
    isCurrent: false,
    slide: 1,
  }),
  officeSelectionSurface({
    revisionId: BASELINE_ID,
    sourceSha256: BASELINE_SHA,
    isCurrent: false,
    slide: 2,
  }),
];

const OFFICE_AGENT = {
  name: "office",
  description: "Work with Word, Excel, and PowerPoint files.",
  model: null,
  tool_groups: ["file:read", "file:write"],
  skills: [],
  product: {
    id: "builtin:office",
    display_name: "Office",
    origin: "builtin",
    category: "create",
    icon: "files",
    status: "available",
    required_tools: [
      "office_inspect",
      "office_generate",
      "office_edit",
      "office_render",
    ],
    missing_requirements: [],
    data_access: ["thread_uploads", "thread_workspace", "thread_outputs"],
    starter_prompts: [],
    launch: {
      kind: "chat",
      path: "/workspace/agents/office/chats/new",
      project_kind: null,
    },
    management: { can_edit: false, can_delete: false },
  },
};

test.describe("Office projects", () => {
  test("Recent opens a verified project preview and revision evidence", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [OFFICE_PROJECT],
      officeSelectionSurfaces: OFFICE_SELECTION_SURFACES,
    });

    await page.goto("/workspace/office");

    await expect(page.getByRole("heading", { name: "Office" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Quarterly update.pptx")).toBeVisible();
    await expect(page.getByText("Review pending")).toBeVisible();
    await expect(
      page.getByAltText("Quarterly update.pptx, page 1 preview"),
    ).toBeVisible();
    await page
      .getByRole("searchbox", { name: "Search Office projects" })
      .fill("missing project");
    await expect(page.getByText("No matching projects")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByText("Quarterly update.pptx")).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-recent-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByText("Quarterly update.pptx").click();
    await page.waitForURL(`**/workspace/office/projects/${PROJECT_ID}`);

    await expect(
      page.getByRole("heading", { name: "Quarterly update.pptx" }),
    ).toBeVisible();
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(page.getByText("Source SHA-256")).toBeVisible();
    await expect(page.getByText(SHA)).toBeVisible();
    await expect(page.getByText("Revision history")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Continue in chat" }),
    ).toHaveAttribute(
      "href",
      `/workspace/agents/office/chats/${MOCK_THREAD_ID}`,
    );
    await page.getByRole("button", { name: "Page 2 of 2" }).click();
    await expect(page.getByText("Page 2 of 2")).toBeVisible();

    await page.getByRole("button", { name: "View revision 1" }).click();
    await page.waitForURL(
      `**/workspace/office/projects/${PROJECT_ID}/revisions/${BASELINE_ID}`,
    );
    await expect(page.getByText("Historical").first()).toBeVisible();
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(
      page.getByAltText("Quarterly update.pptx, page 1 preview").last(),
    ).toBeVisible();
    await expect(page.getByText(BASELINE_SHA)).toBeVisible();
    await expect(page.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      new RegExp(`/revisions/${BASELINE_ID}/artifact$`),
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-project-historical-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("button", { name: "View revision 2" }).click();
    await page.waitForURL(`**/workspace/office/projects/${PROJECT_ID}`);
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(page.getByText(SHA)).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-project-desktop.png"),
        fullPage: true,
      });
    }
  });

  test("generated project shows native receipt without requesting a parent comparison", async ({
    page,
  }, testInfo) => {
    let comparisonRequests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/comparison")) comparisonRequests += 1;
    });
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [GENERATED_PROJECT],
    });

    await page.goto("/workspace/office");
    await expect(page.getByText("Native launch deck.pptx")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Generated", { exact: true })).toBeVisible();
    await expect(
      page.getByAltText("Native launch deck.pptx, page 1 preview"),
    ).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-generation-recent-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByText("Native launch deck.pptx").click();
    await page.waitForURL(
      `**/workspace/office/projects/${GENERATED_PROJECT_ID}`,
    );
    await expect(page.getByText("Page 1 of 1")).toBeVisible();
    await expect(page.getByText("Recorded")).toBeVisible();
    await expect(page.getByText("Generated slides")).toBeVisible();
    await expect(page.getByText("Native objects")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Compare" })).toBeDisabled();
    await expect(page.getByRole("tab", { name: "Changes" })).toBeEnabled();

    await page.getByRole("tab", { name: "Changes" }).click();
    await expect(page.getByText("Generation evidence")).toBeVisible();
    await expect(page.getByText("vassilflow-native-pptx v1")).toBeVisible();
    await expect(page.getByText(GENERATED_INTENT_SHA)).toBeVisible();
    await expect(
      page.getByText("Open the product launch review"),
    ).toBeVisible();
    await expect(
      page.getByText("/slide[1]/shape[@id=3]", { exact: true }),
    ).toBeVisible();
    expect(comparisonRequests).toBe(0);
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-generation-evidence-desktop.png"),
        fullPage: true,
      });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(
      dimensions.clientWidth + 1,
    );
    const generationBounds = await page
      .getByTestId("office-generation-evidence")
      .boundingBox();
    const detailsBounds = await page
      .locator('aside[aria-label="Project details"]')
      .boundingBox();
    expect(generationBounds).not.toBeNull();
    expect(detailsBounds).not.toBeNull();
    expect(detailsBounds!.y).toBeGreaterThanOrEqual(
      generationBounds!.y + generationBounds!.height - 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-generation-evidence-mobile.png"),
        fullPage: true,
      });
    }
  });

  test("selects, reviews, and approves an exact PowerPoint object edit", async ({
    page,
  }, testInfo) => {
    const expectedSelection = {
      kind: "pptx_object",
      project_id: PROJECT_ID,
      revision_id: REVISION_ID,
      source_sha256: SHA,
      slide_index: 1,
      object_path: "/slide[1]/shape[@id=2]",
      object_fingerprint: TITLE_OBJECT_FINGERPRINT,
    };
    const approvalRequestId = `office-selection-approval:${"7".repeat(64)}`;
    const editArgs = {
      source_path: null,
      output_path: "/mnt/user-data/outputs/quarterly-update-blue.pptx",
      operations: [
        {
          type: "format_pptx_shapes",
          shapes: {
            targets: [
              {
                path: expectedSelection.object_path,
                expected_name: "Quarter title",
              },
            ],
          },
          formatting: {
            fill: { type: "solid", color: "1F4E79" },
          },
        },
      ],
    };
    let submittedContext: unknown;
    let submittedMessageContext: unknown;
    let submittedApproval: unknown;
    let submittedApprovalContext: unknown;
    let submittedApprovalMessageContext: unknown;
    let approvalStateMessages: unknown[] = [];
    const runStreamMessages = (route: Route, callIndex: number) => {
      const body = route.request().postDataJSON() as {
        context?: { office_selection_request?: unknown };
        input?: {
          messages?: Array<Record<string, unknown>>;
        };
      };
      const inputMessages = body.input?.messages ?? [];
      const lastMessage = inputMessages.at(-1);
      const additionalKwargs = lastMessage?.additional_kwargs as
        | {
            office_selection_request?: unknown;
            human_input_response?: unknown;
          }
        | undefined;
      if (callIndex === 1) {
        submittedContext = body.context?.office_selection_request;
        submittedMessageContext = additionalKwargs?.office_selection_request;
        const proposalMessage = {
          type: "ai",
          id: "msg-office-edit-proposal",
          content: "",
          additional_kwargs: {},
          response_metadata: {},
          tool_calls: [
            {
              id: "call-office-edit",
              name: "office_edit",
              args: editArgs,
              type: "tool_call",
            },
          ],
          invalid_tool_calls: [],
        };
        const approvalMessage = {
          type: "tool",
          id: approvalRequestId,
          name: "office_edit",
          tool_call_id: "call-office-edit",
          content:
            "Review the exact selected-object Office edit before it is applied.",
          artifact: {
            human_input: {
              version: 1,
              kind: "human_input_request",
              source: "office_selection_approval",
              request_id: approvalRequestId,
              tool_call_id: "call-office-edit",
              clarification_type: "office_edit_approval",
              title: "Review Office edit",
              question:
                "Apply these operations to the selected PowerPoint object?",
              context: `\`\`\`json\n${JSON.stringify(
                { selection: expectedSelection, tool_args: editArgs },
                null,
                2,
              )}\n\`\`\``,
              input_mode: "single_choice",
              options: [
                {
                  id: "approve",
                  label: "Approve and apply",
                  value: "approve",
                },
                { id: "cancel", label: "Cancel", value: "cancel" },
              ],
              proposal_sha256: "7".repeat(64),
            },
          },
        };
        approvalStateMessages = [
          ...inputMessages,
          proposalMessage,
          approvalMessage,
        ];
        return approvalStateMessages;
      }

      submittedApproval = additionalKwargs?.human_input_response;
      submittedApprovalContext = body.context?.office_selection_request;
      submittedApprovalMessageContext =
        additionalKwargs?.office_selection_request;
      return [
        ...approvalStateMessages,
        ...inputMessages,
        {
          type: "ai",
          id: "msg-office-edit-complete",
          content: "Office edit applied.",
          additional_kwargs: {},
          response_metadata: {},
          tool_calls: [],
          invalid_tool_calls: [],
        },
      ];
    };
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [OFFICE_PROJECT],
      officeSelectionSurfaces: OFFICE_SELECTION_SURFACES,
      runStreamMessages,
    });

    await page.goto(`/workspace/office/projects/${PROJECT_ID}`);
    const objectButton = page
      .getByRole("region", { name: "Objects" })
      .getByRole("button", { name: "Select Quarter title" });
    await expect(objectButton).toBeVisible({ timeout: 15_000 });
    await objectButton.click();

    await expect(page.getByTestId("office-selected-object")).toContainText(
      "Quarter title",
    );
    await expect(
      page.getByTestId("office-object-overlay-66666666"),
    ).toHaveClass(/ring-2/);
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-object-selection-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("link", { name: "Ask Office Agent" }).click();
    await expect(page).toHaveURL(/\/workspace\/agents\/office\/chats\/new\?/);
    expect(decodeURIComponent(page.url())).not.toContain("Quarter title");
    expect(decodeURIComponent(page.url())).not.toContain("Q4 company update");
    await expect(page.getByTestId("office-selection-chip")).toContainText(
      "Slide 1 / Quarter title",
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-selection-chat-desktop.png"),
        fullPage: true,
      });
    }

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toHaveValue(
      "Describe the change you want for this object.",
    );
    await textarea.fill("Make the title blue.");
    await textarea.press("Enter");

    await expect
      .poll(() => submittedContext, { timeout: 10_000 })
      .toEqual(expectedSelection);
    expect(submittedMessageContext).toEqual(expectedSelection);
    const approvalCard = page.getByTestId("human-input-card");
    await expect(approvalCard).toBeVisible({ timeout: 10_000 });
    await expect(approvalCard).toContainText("Review Office edit");
    await expect(approvalCard).toContainText(expectedSelection.object_path);
    await expect(approvalCard).toContainText("1F4E79");
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-selection-approval-desktop.png"),
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(
        approvalCard.getByRole("button", { name: "Approve and apply" }),
      ).toBeInViewport();
      await expect(
        approvalCard.getByRole("button", { name: "Cancel" }),
      ).toBeInViewport();
      const viewportWidth = await page.evaluate(() => ({
        client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      expect(viewportWidth.scroll).toBeLessThanOrEqual(viewportWidth.client);
      await page.screenshot({
        path: testInfo.outputPath("office-selection-approval-mobile.png"),
      });
      await page.setViewportSize({ width: 1280, height: 720 });
    }

    await approvalCard
      .getByRole("button", { name: "Approve and apply" })
      .click();
    await expect
      .poll(() => submittedApproval, { timeout: 10_000 })
      .toEqual({
        version: 1,
        kind: "human_input_response",
        source: "office_selection_approval",
        request_id: approvalRequestId,
        response_kind: "option",
        option_id: "approve",
        value: "approve",
      });
    expect(submittedApprovalContext).toEqual(expectedSelection);
    expect(submittedApprovalMessageContext).toEqual(expectedSelection);
    await expect(page.getByText("Office edit applied.")).toBeVisible({
      timeout: 10_000,
    });
    await expect(approvalCard).toContainText("Answered");
    await expect(page.getByTestId("office-selection-chip")).toBeVisible();
  });

  test("compares evidence, approves a final, and restores append-only", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [OFFICE_PROJECT],
      officeSelectionSurfaces: OFFICE_SELECTION_SURFACES,
    });

    await page.goto(`/workspace/office/projects/${PROJECT_ID}`);
    await expect(page.getByText("Page 1 of 2")).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("tab", { name: "Compare" }).click();
    await expect(page.getByText("Before render")).toBeVisible();
    await expect(page.getByText("After render")).toBeVisible();
    await expect(page.getByAltText("Before render, Page 1 of 2")).toBeVisible();
    await expect(page.getByAltText("After render, Page 1 of 2")).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-project-compare-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("tab", { name: "Changes" }).click();
    await expect(page.getByText("Semantic receipt")).toBeVisible();
    await expect(page.getByText("replace-quarter-title")).toBeVisible();
    await expect(
      page.getByText("/slide[1]/shape[@id=2]", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText("Q3 company update")).toBeVisible();
    await expect(page.getByText("Q4 company update")).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-project-changes-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await page.getByLabel("Review note").fill("Checked both rendered pages.");
    await page.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("Revision approved.")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Mark final" }),
    ).toBeEnabled();

    await page.getByRole("button", { name: "Mark final" }).click();
    await expect(page.getByText("Final artifact selected.")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Download final" }),
    ).toHaveAttribute(
      "href",
      new RegExp(`/api/office/projects/${PROJECT_ID}/final/artifact$`),
    );
    await page.getByRole("button", { name: "Render", exact: true }).click();
    await expect(page.getByText("All slides rendered.")).toBeVisible();
    await expect(page.getByText("Review pending")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Download final" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "View revision 1" }).click();
    await page.waitForURL(
      `**/workspace/office/projects/${PROJECT_ID}/revisions/${BASELINE_ID}`,
    );
    await page.getByRole("button", { name: "Restore revision 1" }).click();
    await page
      .getByRole("button", { name: "Restore revision", exact: true })
      .click();
    await page.waitForURL(`**/workspace/office/projects/${PROJECT_ID}`);

    await expect(page.getByText("Revision 3").first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: "View revision 1" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "View revision 2" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "View revision 3" }),
    ).toBeVisible();
    await expect(page.getByText("Final", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Download final" }),
    ).toBeVisible();
  });

  test("New presentation opens the Office Agent with a typed starter", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [OFFICE_PROJECT],
      officeSelectionSurfaces: OFFICE_SELECTION_SURFACES,
    });

    await page.goto("/workspace/office");
    await page.getByRole("button", { name: "New" }).click();
    await page.getByRole("menuitem", { name: "Presentation" }).click();

    await expect(page).toHaveURL(
      /\/workspace\/agents\/office\/chats\/new\?starter=presentation$/,
    );
    await expect(page.getByRole("textbox").first()).toHaveValue(
      "Create a new PowerPoint presentation.",
    );
  });

  test("preview remains bounded on mobile", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      agents: [OFFICE_AGENT],
      officeProjects: [OFFICE_PROJECT],
      officeSelectionSurfaces: OFFICE_SELECTION_SURFACES,
    });

    await page.goto("/workspace/office");
    await expect(page.getByText("Quarterly update.pptx")).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByAltText("Quarterly update.pptx, page 1 preview"),
    ).toBeVisible();
    const recentDimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(recentDimensions.scrollWidth).toBeLessThanOrEqual(
      recentDimensions.clientWidth + 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-recent-mobile.png"),
        fullPage: true,
      });
    }

    await page.getByText("Quarterly update.pptx").click();
    await page.waitForURL(`**/workspace/office/projects/${PROJECT_ID}`);
    await expect(page.getByText("Page 1 of 2")).toBeVisible({
      timeout: 15_000,
    });
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(
      dimensions.clientWidth + 1,
    );
    await expect(
      page.getByAltText("Quarterly update.pptx, page 1 preview").last(),
    ).toBeVisible();
    const mobileObjectButton = page
      .getByRole("region", { name: "Objects" })
      .getByRole("button", { name: "Select Quarter title" });
    await expect(mobileObjectButton).toBeVisible();
    await mobileObjectButton.click();
    await expect(page.getByTestId("office-selected-object")).toContainText(
      "Quarter title",
    );
    const selectedDimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(selectedDimensions.scrollWidth).toBeLessThanOrEqual(
      selectedDimensions.clientWidth + 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-object-selection-mobile.png"),
        fullPage: true,
      });
    }
    await page.getByRole("tab", { name: "Compare" }).click();
    await expect(page.getByText("Before render")).toBeVisible();
    await expect(page.getByText("After render")).toBeVisible();
    const compareDimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(compareDimensions.scrollWidth).toBeLessThanOrEqual(
      compareDimensions.clientWidth + 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-project-mobile.png"),
        fullPage: true,
      });
    }
  });
});

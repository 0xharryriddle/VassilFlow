import { expect, test } from "@playwright/test";

import {
  mockLangGraphAPI,
  type MockOfficeTemplate,
  type MockOfficeTemplateVersion,
} from "./utils/mock-api";

const TEMPLATE_ID = `oft_${"1".repeat(32)}`;
const TEXT_CANDIDATE_ID = `otc_${"2".repeat(32)}`;
const PICTURE_CANDIDATE_ID = `otc_${"3".repeat(32)}`;
const SOURCE_SHA = "a".repeat(64);

function createTemplate(): MockOfficeTemplate {
  const version: MockOfficeTemplateVersion = {
    template_id: TEMPLATE_ID,
    version: 1,
    status: "draft",
    format: "pptx",
    filename: "quarterly-template.pptx",
    created_at: "2026-07-17T10:00:00Z",
    updated_at: "2026-07-17T10:00:00Z",
    published_at: null,
    source: { sha256: SOURCE_SHA, size_bytes: 128_000 },
    validation_status: "valid",
    slide_count: 2,
    object_count: 4,
    preflight_finding_count: 0,
    preflight_findings_by_severity: {},
    slot_candidate_count: 2,
    slot_count: 0,
    render: {
      status: "not_recorded",
      evidence_id: null,
      created_at: null,
      source_sha256: null,
      page_count: 0,
      rendered_page_count: 0,
      pipeline_fingerprint: null,
      renderer: null,
      renderer_version: null,
      visual_review_status: "not_performed",
      reviewed_at: null,
      reviewed_by: null,
      review_note: null,
      preview_pages: [],
    },
    validation: { valid: true },
    locked_policy: {
      fixed_slide_count: 2,
      structure_fingerprint: "b".repeat(64),
      regions: "all_except_slots",
    },
    slot_candidates: [
      {
        candidate_id: TEXT_CANDIDATE_ID,
        source_fingerprint: "c".repeat(64),
        type: "text",
        path: "/slide[1]/shape[@id=2]",
        slide_index: 1,
        default_label: "Quarter title",
        selector: {
          path: "/slide[1]/shape[@id=2]",
          expected_text: "Q3 company update",
        },
        source: {
          name: "Quarter title",
          text: "Q3 company update",
          text_sha256: "d".repeat(64),
        },
      },
      {
        candidate_id: PICTURE_CANDIDATE_ID,
        source_fingerprint: "e".repeat(64),
        type: "picture",
        path: "/slide[2]/picture[@id=4]",
        slide_index: 2,
        default_label: "Hero image",
        selector: {
          path: "/slide[2]/picture[@id=4]",
          expected_name: "Hero image",
          expected_source_sha256: "f".repeat(64),
        },
        source: {
          name: "Hero image",
          sha256: "f".repeat(64),
          content_type: "image/png",
        },
      },
    ],
    slots: [],
  };

  return {
    template_id: TEMPLATE_ID,
    title: "Quarterly company deck",
    format: "pptx",
    owner_scope: "user",
    created_at: "2026-07-17T10:00:00Z",
    updated_at: "2026-07-17T10:00:00Z",
    latest_version: 1,
    draft_version: 1,
    published_versions: [],
    archived: false,
    status: "draft",
    active_version: { ...version },
    versions: [{ ...version }],
    version_details: [version],
  };
}

function createPublishedTemplate(): MockOfficeTemplate {
  const template = createTemplate();
  const slot = {
    key: "headline",
    label: "Quarter title",
    type: "text",
    required: true,
    candidate_id: TEXT_CANDIDATE_ID,
    source_fingerprint: "c".repeat(64),
    selector: {
      path: "/slide[1]/shape[@id=2]",
      expected_text: "Q3 company update",
    },
    constraints: { max_length: 200 },
    allowed_operations: ["replace_pptx_text"],
  };
  for (const version of [
    template.active_version,
    ...template.versions,
    ...(template.version_details ?? []),
  ]) {
    version.status = "published";
    version.slot_count = 1;
    version.slots = [slot];
    version.published_at = "2026-07-17T10:15:00Z";
  }
  template.status = "published";
  template.draft_version = null;
  template.published_versions = [1];
  return template;
}

test.describe("Office templates", () => {
  test("catalog and import route use real template resources", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, { officeTemplates: [createTemplate()] });

    await page.goto("/workspace/office/templates");
    await expect(page.getByRole("heading", { name: "Office" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("link", { name: "Templates" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByText("Quarterly company deck")).toBeVisible();
    await expect(page.getByText("Draft").first()).toBeVisible();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-template-catalog-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("link", { name: "Import template" }).click();
    await page.waitForURL("**/workspace/office/templates/new");
    await page.locator('input[type="file"]').setInputFiles({
      name: "quarterly-template.pptx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      buffer: Buffer.from("mock-pptx"),
    });
    await page.getByLabel("Template name").fill("Quarterly company deck");
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await page.waitForURL(`**/workspace/office/templates/${TEMPLATE_ID}`);
    await expect(
      page.getByRole("heading", { name: "Quarterly company deck" }),
    ).toBeVisible();
  });

  test("maps, renders, reviews, and publishes one immutable version", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, { officeTemplates: [createTemplate()] });
    await page.goto(`/workspace/office/templates/${TEMPLATE_ID}`);

    await expect(
      page.getByRole("heading", { name: "Quarterly company deck" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("No render evidence yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).toBeDisabled();

    await page
      .getByRole("switch", {
        name: "Enable Quarter title as a variable slot",
      })
      .click();
    await page.getByLabel("Key").fill("headline");
    await page.getByRole("button", { name: "Save mapping" }).click();
    await expect(page.getByText("Template mapping saved.")).toBeVisible();
    await expect(page.getByText("1 slot")).toBeVisible();

    await page
      .getByRole("button", { name: "Render all slides" })
      .first()
      .click();
    await expect(page.getByText("All slides rendered.")).toBeVisible();
    await expect(
      page.getByAltText("Quarterly company deck, page 1 preview").last(),
    ).toBeVisible();

    await page.getByRole("button", { name: "Mark reviewed" }).click();
    await expect(page.getByText("Visual review saved.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish" })).toBeEnabled();
    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText("Template version published.")).toBeVisible();
    await expect(page.getByText("Published").first()).toBeVisible();
    await expect(
      page.getByRole("switch", {
        name: "Enable Quarter title as a variable slot",
      }),
    ).toBeDisabled();
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-template-published-desktop.png"),
        fullPage: true,
      });
    }

    await page.getByRole("link", { name: "Use template" }).click();
    await page.waitForURL(
      `**/workspace/office/templates/${TEMPLATE_ID}/use?version=1`,
    );
    await page.getByLabel("Quarter title").fill("Q4 customer update");
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-template-use-desktop.png"),
        fullPage: true,
      });
    }
    await page.getByRole("button", { name: "Create project" }).click();
    await page.waitForURL(`**/workspace/office/projects/ofp_${"7".repeat(32)}`);
    await expect(
      page.getByRole("heading", { name: "Quarterly company deck.pptx" }),
    ).toBeVisible();
    await expect(page.getByText("Page 1 of 2")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Template v1" }),
    ).toHaveAttribute("href", `/workspace/office/templates/${TEMPLATE_ID}`);
  });

  test("template detail stays within a 390-pixel viewport", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { officeTemplates: [createTemplate()] });
    await page.goto(`/workspace/office/templates/${TEMPLATE_ID}`);
    await expect(page.getByText("Quarter title")).toBeVisible({
      timeout: 15_000,
    });

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(
      dimensions.clientWidth + 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-template-mobile.png"),
        fullPage: true,
      });
    }
  });

  test("template project form stays within a 390-pixel viewport", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      officeTemplates: [createPublishedTemplate()],
    });
    await page.goto(`/workspace/office/templates/${TEMPLATE_ID}/use?version=1`);
    await expect(page.getByLabel("Quarter title")).toBeVisible({
      timeout: 15_000,
    });

    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(
      dimensions.clientWidth + 1,
    );
    if (process.env.CAPTURE_OFFICE_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("office-template-use-mobile.png"),
        fullPage: true,
      });
    }
  });
});

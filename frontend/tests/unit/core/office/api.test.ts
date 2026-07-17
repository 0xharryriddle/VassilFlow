import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "https://gateway.test",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  collectOfficePreviewPages,
  compareOfficeRevision,
  getOfficeProject,
  getOfficeRevision,
  getOfficeTemplate,
  getOfficeTemplateVersion,
  importOfficeTemplate,
  instantiateOfficeTemplate,
  listOfficeProjects,
  listOfficeRevisions,
  listOfficeTemplates,
  officeArtifactURL,
  officeFinalArtifactURL,
  officeResourceURL,
  officeTemplateSourceURL,
  publishOfficeTemplate,
  renderOfficeProjectRevision,
  renderOfficeTemplate,
  reviewOfficeTemplateRender,
  reviewOfficeProjectRevision,
  restoreOfficeProjectRevision,
  selectOfficeProjectFinal,
  type OfficeRenderEvidence,
  updateOfficeTemplateSlots,
} from "@/core/office";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("Office Project API", () => {
  test("uses the project read endpoints", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ projects: [] }))
      .mockResolvedValueOnce(jsonResponse({ project_id: "ofp_1" }))
      .mockResolvedValueOnce(
        jsonResponse({ project_id: "ofp_1", revisions: [] }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          project_id: "ofp_1",
          revision: { revision_id: "ofr_2" },
        }),
      );

    await listOfficeProjects(20);
    await getOfficeProject("ofp_1");
    await listOfficeRevisions("ofp_1", 10);
    await getOfficeRevision("ofp_1", "ofr_2");

    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "https://gateway.test/api/office/projects?limit=20",
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "https://gateway.test/api/office/projects/ofp_1",
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      3,
      "https://gateway.test/api/office/projects/ofp_1/revisions?limit=10",
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      4,
      "https://gateway.test/api/office/projects/ofp_1/revisions/ofr_2",
    );
  });

  test("uses evidence-bound project workflow endpoints", async () => {
    mockedFetch.mockImplementation(async () => jsonResponse({ ok: true }));

    await compareOfficeRevision("ofp_1", "ofr_2");
    await renderOfficeProjectRevision("ofp_1", "ofr_2");
    await reviewOfficeProjectRevision(
      "ofp_1",
      "ofr_2",
      ["ofe_3", "ofe_4"],
      "approved",
      "Reviewed all pages",
    );
    await selectOfficeProjectFinal("ofp_1", "ofr_2", "ofv_5", "ofr_2");
    await restoreOfficeProjectRevision("ofp_1", "ofr_1", "ofr_2");

    expect(mockedFetch.mock.calls[0]?.[0]).toMatch(/\/comparison$/);
    expect(mockedFetch.mock.calls[1]?.[0]).toMatch(/\/render$/);
    expect(mockedFetch.mock.calls[1]?.[1]).toEqual({ method: "POST" });
    expect(mockedFetch.mock.calls[2]?.[0]).toMatch(/\/reviews$/);
    expect(JSON.parse(mockedFetch.mock.calls[2]?.[1]?.body as string)).toEqual({
      status: "approved",
      evidence_ids: ["ofe_3", "ofe_4"],
      note: "Reviewed all pages",
    });
    expect(mockedFetch.mock.calls[3]?.[0]).toMatch(/\/projects\/ofp_1\/final$/);
    expect(JSON.parse(mockedFetch.mock.calls[3]?.[1]?.body as string)).toEqual({
      revision_id: "ofr_2",
      review_id: "ofv_5",
      expected_current_revision_id: "ofr_2",
    });
    expect(mockedFetch.mock.calls[4]?.[0]).toMatch(/\/ofr_1\/restore$/);
    expect(JSON.parse(mockedFetch.mock.calls[4]?.[1]?.body as string)).toEqual({
      expected_current_revision_id: "ofr_2",
    });
    expect(officeFinalArtifactURL("ofp_1")).toBe(
      "https://gateway.test/api/office/projects/ofp_1/final/artifact",
    );
  });

  test("builds trusted binary resource URLs against the gateway", () => {
    expect(officeResourceURL("/api/office/preview.png")).toBe(
      "https://gateway.test/api/office/preview.png",
    );
    expect(officeResourceURL("https://cdn.test/preview.png")).toBe(
      "https://cdn.test/preview.png",
    );
    expect(officeArtifactURL("ofp_1", "ofr_2")).toBe(
      "https://gateway.test/api/office/projects/ofp_1/revisions/ofr_2/artifact",
    );
  });

  test("keeps the newest preview when render windows overlap", () => {
    const evidence = [
      {
        evidence_id: "new",
        preview_pages: [
          { page: 2, sha256: "new-page-2" },
          { page: 3, sha256: "page-3" },
        ],
      },
      {
        evidence_id: "old",
        preview_pages: [
          { page: 1, sha256: "page-1" },
          { page: 2, sha256: "old-page-2" },
        ],
      },
    ] as OfficeRenderEvidence[];

    expect(
      collectOfficePreviewPages(evidence).map((page) => [
        page.page,
        page.sha256,
      ]),
    ).toEqual([
      [1, "page-1"],
      [2, "new-page-2"],
      [3, "page-3"],
    ]);
  });
});

describe("Office Template API", () => {
  test("uses typed template management endpoints", async () => {
    const templateId = `oft_${"1".repeat(32)}`;
    const candidateId = `otc_${"2".repeat(32)}`;
    const evidenceId = `otr_${"3".repeat(32)}`;
    const file = new File(["pptx"], "quarterly.pptx", {
      type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    });
    mockedFetch.mockImplementation(async () =>
      jsonResponse({ template_id: templateId }),
    );

    await listOfficeTemplates(25);
    await importOfficeTemplate(file, "Quarterly");
    await getOfficeTemplate(templateId);
    await getOfficeTemplateVersion(templateId, 1);
    await updateOfficeTemplateSlots(templateId, 1, [
      {
        key: "headline",
        label: "Headline",
        type: "text",
        candidate_id: candidateId,
        required: true,
        max_length: 120,
      },
    ]);
    await renderOfficeTemplate(templateId, 1);
    await reviewOfficeTemplateRender(templateId, 1, evidenceId, "reviewed");
    await publishOfficeTemplate(templateId, 1);
    const picture = new File(["png"], "hero.png", { type: "image/png" });
    await instantiateOfficeTemplate(
      templateId,
      1,
      [
        { key: "headline", type: "text", value: "Q4 update" },
        { key: "hero_image", type: "picture", file: picture },
      ],
      "Customer update",
    );

    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "https://gateway.test/api/office/templates?limit=25",
    );
    const importRequest = mockedFetch.mock.calls[1];
    expect(importRequest?.[0]).toBe(
      "https://gateway.test/api/office/templates",
    );
    expect(importRequest?.[1]).toMatchObject({ method: "POST" });
    const form = importRequest?.[1]?.body;
    expect(form).toBeInstanceOf(FormData);
    expect((form as FormData).get("file")).toBe(file);
    expect((form as FormData).get("title")).toBe("Quarterly");
    expect(mockedFetch).toHaveBeenNthCalledWith(
      3,
      `https://gateway.test/api/office/templates/${templateId}`,
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      4,
      `https://gateway.test/api/office/templates/${templateId}/versions/1`,
    );
    expect(mockedFetch.mock.calls[4]?.[0]).toBe(
      `https://gateway.test/api/office/templates/${templateId}/versions/1/slots`,
    );
    expect(mockedFetch.mock.calls[4]?.[1]).toMatchObject({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(mockedFetch.mock.calls[4]?.[1]?.body as string)).toEqual({
      slots: [
        {
          key: "headline",
          label: "Headline",
          type: "text",
          candidate_id: candidateId,
          required: true,
          max_length: 120,
        },
      ],
    });
    expect(mockedFetch.mock.calls[5]?.[0]).toMatch(/\/render$/);
    expect(mockedFetch.mock.calls[5]?.[1]).toMatchObject({ method: "POST" });
    expect(mockedFetch.mock.calls[6]?.[0]).toContain(
      `/renders/${evidenceId}/review`,
    );
    expect(JSON.parse(mockedFetch.mock.calls[6]?.[1]?.body as string)).toEqual({
      status: "reviewed",
    });
    expect(mockedFetch.mock.calls[7]?.[0]).toMatch(/\/publish$/);
    const instantiateRequest = mockedFetch.mock.calls[8];
    expect(instantiateRequest?.[0]).toMatch(/\/versions\/1\/instantiate$/);
    expect(instantiateRequest?.[1]).toMatchObject({ method: "POST" });
    const instantiateForm = instantiateRequest?.[1]?.body as FormData;
    expect(JSON.parse(instantiateForm.get("bindings_json") as string)).toEqual({
      bindings: [
        { key: "headline", type: "text", value: "Q4 update" },
        { key: "hero_image", type: "picture", upload_index: 0 },
      ],
    });
    expect(instantiateForm.get("title")).toBe("Customer update");
    expect(instantiateForm.getAll("files")).toEqual([picture]);
  });

  test("builds a permission-checked source URL and preserves API details", async () => {
    const templateId = `oft_${"a".repeat(32)}`;
    expect(officeTemplateSourceURL(templateId, 2)).toBe(
      `https://gateway.test/api/office/templates/${templateId}/versions/2/source`,
    );
    mockedFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Current evidence is stale." }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(publishOfficeTemplate(templateId, 2)).rejects.toThrow(
      "Current evidence is stale.",
    );
  });
});

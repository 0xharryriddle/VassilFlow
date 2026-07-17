import { describe, expect, it } from "@rstest/core";

import {
  buildOfficeObjectSelectionRequest,
  buildOfficeSelectionChatHref,
  officeSelectionSearchParams,
  parseOfficeSelectionSearchParams,
  resolveOfficeSelectionObject,
} from "@/core/office/selection";
import type { OfficePptxSelectionSurface } from "@/core/office/types";

const surface: OfficePptxSelectionSurface = {
  schema: "vassilflow.office.pptx_object_selection.v1",
  format: "pptx",
  project_id: `ofp_${"1".repeat(32)}`,
  revision_id: `ofr_${"2".repeat(32)}`,
  is_current: true,
  source_sha256: "a".repeat(64),
  slide: {
    index: 1,
    path: "/slide[1]",
    title: null,
    width_emu: 100,
    height_emu: 100,
  },
  object_count: 1,
  objects_returned: 1,
  objects_truncated: false,
  objects: [
    {
      path: "/slide[1]/shape[@id=3]",
      parent_path: "/slide[1]",
      kind: "text_box",
      name: "Headline",
      z_order: 1,
      identity_source: "cNvPr.id",
      selection_status: "selectable",
      allowed_operations: ["replace_pptx_text"],
      geometry: {},
      overlay: {
        left_percent: 10,
        top_percent: 10,
        width_percent: 40,
        height_percent: 20,
        rotation_degrees: null,
      },
      text_preview: "Quarterly review",
      text_truncated: false,
      object_fingerprint: "b".repeat(64),
    },
  ],
};

describe("Office selection routing", () => {
  it("round-trips a typed object selection without document text", () => {
    const request = buildOfficeObjectSelectionRequest(
      surface,
      surface.objects[0]!,
    );
    const params = officeSelectionSearchParams(request);

    expect(parseOfficeSelectionSearchParams(params)).toEqual(request);
    expect(params.toString()).not.toContain("Quarterly");
    expect(buildOfficeSelectionChatHref(request)).toContain(
      "starter=edit-selection",
    );
  });

  it("rejects malformed or incomplete query identities", () => {
    const request = buildOfficeObjectSelectionRequest(
      surface,
      surface.objects[0]!,
    );
    const params = officeSelectionSearchParams(request);
    params.set("office_object_fingerprint", "not-a-hash");

    expect(parseOfficeSelectionSearchParams(params)).toBeNull();
    expect(parseOfficeSelectionSearchParams(new URLSearchParams())).toBeNull();
  });

  it("resolves only an exact source, path, and fingerprint", () => {
    const request = buildOfficeObjectSelectionRequest(
      surface,
      surface.objects[0]!,
    );

    expect(resolveOfficeSelectionObject(surface, request)).toEqual(
      surface.objects[0],
    );
    expect(
      resolveOfficeSelectionObject(surface, {
        ...request,
        source_sha256: "c".repeat(64),
      }),
    ).toBeNull();
  });
});

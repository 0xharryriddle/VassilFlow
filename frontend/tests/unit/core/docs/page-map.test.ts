import { describe, expect, it } from "@rstest/core";
import type { PageMapItem } from "nextra";

import { buildDocsPageMap } from "@/core/docs/page-map";

describe("buildDocsPageMap", () => {
  it("removes application pages and prefixes only documentation routes", () => {
    const input: PageMapItem[] = [
      {
        data: {
          index: { title: "Overview" },
          introduction: { title: "Introduction" },
          workspace: { type: "page" },
        },
      },
      { name: "index", route: "/" },
      {
        name: "introduction",
        route: "/introduction",
        children: [
          {
            name: "core-concepts",
            route: "/introduction/core-concepts",
          },
        ],
      },
      {
        name: "workspace",
        route: "/workspace",
        children: [
          {
            name: "template",
            route: "/workspace/sample/templates/[template_id]",
          },
        ],
      },
    ];

    const result = buildDocsPageMap("/en/docs", input);

    expect(result).toEqual([
      {
        data: {
          index: { title: "Overview" },
          introduction: { title: "Introduction" },
        },
      },
      { name: "index", route: "/en/docs" },
      {
        name: "introduction",
        route: "/en/docs/introduction",
        children: [
          {
            name: "core-concepts",
            route: "/en/docs/introduction/core-concepts",
          },
        ],
      },
    ]);
    expect(input[3]).toHaveProperty("name", "workspace");
  });

  it("normalizes locale-prefixed routes without duplicating the locale", () => {
    const result = buildDocsPageMap("/zh/docs", [
      { name: "index", route: "/zh" },
      { name: "reference", route: "/zh/reference" },
      { name: "ready", route: "/zh/docs/tutorials/ready" },
    ]);

    expect(result).toEqual([
      { name: "index", route: "/zh/docs" },
      { name: "reference", route: "/zh/docs/reference" },
      { name: "ready", route: "/zh/docs/tutorials/ready" },
    ]);
  });
});

import { describe, expect, test } from "@rstest/core";

import {
  APP_DOCS_REPOSITORY_BASE,
  APP_REPOSITORY_API_URL,
  APP_REPOSITORY_URL,
} from "@/core/brand";

describe("VassilFlow brand constants", () => {
  test("point repository surfaces at the VassilFlow repo", () => {
    expect(APP_REPOSITORY_URL).toBe(
      "https://github.com/linhlln1104/VassilFlow",
    );
    expect(APP_REPOSITORY_API_URL).toBe(
      "https://api.github.com/repos/linhlln1104/VassilFlow",
    );
    expect(APP_DOCS_REPOSITORY_BASE).toBe(
      "https://github.com/linhlln1104/VassilFlow/tree/main/frontend/src/content",
    );
  });
});

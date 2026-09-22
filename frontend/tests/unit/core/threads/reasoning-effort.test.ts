import { describe, expect, test } from "@rstest/core";

import { resolveReasoningEffort } from "@/core/threads/reasoning-effort";

describe("composer reasoning effort", () => {
  test.each([
    ["thinking", "low"],
    ["pro", "medium"],
    ["ultra", "high"],
    ["flash", undefined],
    [undefined, undefined],
  ] as const)(
    "derives %s mode as %s when no effort was saved",
    (mode, expected) => {
      expect(resolveReasoningEffort({ mode })).toBe(expected);
    },
  );

  test.each(["minimal", "low", "medium", "high"] as const)(
    "keeps explicit %s effort instead of the mode default",
    (reasoning_effort) => {
      const context = { mode: "ultra" as const, reasoning_effort };
      expect(resolveReasoningEffort(context)).toBe(reasoning_effort);
      expect(context).toEqual({ mode: "ultra", reasoning_effort });
    },
  );
});

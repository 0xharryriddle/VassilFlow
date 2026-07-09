import { describe, expect, test } from "@rstest/core";

import {
  getChangedFileCount,
  getWorkspaceChangeBadgeLabel,
  getWorkspaceChangeLineClass,
  sortWorkspaceChanges,
} from "@/core/workspace-changes/summary";
import type {
  WorkspaceChangeSummary,
  WorkspaceFileChange,
} from "@/core/workspace-changes/types";

function summary(
  overrides: Partial<WorkspaceChangeSummary> = {},
): WorkspaceChangeSummary {
  return {
    created: 0,
    modified: 0,
    deleted: 0,
    additions: 0,
    deletions: 0,
    truncated: false,
    ...overrides,
  };
}

function file(
  path: string,
  status: WorkspaceFileChange["status"],
): WorkspaceFileChange {
  return {
    path,
    root: "workspace",
    status,
    binary: false,
    sensitive: false,
    size_before: null,
    size_after: 1,
    sha256_before: null,
    sha256_after: "abc",
    diff: "",
    diff_truncated: false,
    diff_unavailable_reason: null,
    additions: 0,
    deletions: 0,
  };
}

describe("workspace change summary helpers", () => {
  test("builds changed-file counts and badge labels", () => {
    const value = summary({
      created: 1,
      modified: 2,
      deleted: 1,
      additions: 12,
      deletions: 4,
    });

    expect(getChangedFileCount(value)).toBe(4);
    expect(getWorkspaceChangeBadgeLabel(value)).toBe("4 files changed +12 -4");
  });

  test("classifies diff headers without swallowing content lines", () => {
    expect(getWorkspaceChangeLineClass("--- a/file.txt")).toBe("meta");
    expect(getWorkspaceChangeLineClass("+++ b/file.txt")).toBe("meta");
    expect(getWorkspaceChangeLineClass("@@ -1 +1 @@")).toBe("hunk");
    expect(getWorkspaceChangeLineClass("-old")).toBe("deletion");
    expect(getWorkspaceChangeLineClass("+new")).toBe("addition");
    expect(getWorkspaceChangeLineClass("+++added")).toBe("addition");
    expect(getWorkspaceChangeLineClass("---removed")).toBe("deletion");
  });

  test("sorts created, modified, deleted changes by path", () => {
    const sorted = sortWorkspaceChanges([
      file("/mnt/user-data/workspace/z.txt", "deleted"),
      file("/mnt/user-data/workspace/b.txt", "created"),
      file("/mnt/user-data/workspace/a.txt", "created"),
      file("/mnt/user-data/workspace/m.txt", "modified"),
    ]);

    expect(sorted.map((item) => `${item.status}:${item.path}`)).toEqual([
      "created:/mnt/user-data/workspace/a.txt",
      "created:/mnt/user-data/workspace/b.txt",
      "modified:/mnt/user-data/workspace/m.txt",
      "deleted:/mnt/user-data/workspace/z.txt",
    ]);
  });
});

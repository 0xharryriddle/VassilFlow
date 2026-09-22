import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import {
  buildThreadSubmitMessages,
  getVisibleOptimisticMessages,
  mergeMessages,
} from "@/core/threads/hooks";
import {
  classifySubmissionError,
  preserveFailedSubmission,
} from "@/core/threads/submission-error";

const uploadedFile = {
  filename: "report.csv",
  size: 42,
  path: "/uploads/report.csv",
  status: "uploaded",
};
const human: Message = {
  id: "local-human",
  type: "human",
  content: [{ type: "text", text: "Read my report" }],
  additional_kwargs: { files: [uploadedFile] },
};

test("a pre-checkpoint failure retains submitted text and uploaded files but removes transient task indicators", () => {
  const failed = preserveFailedSubmission([
    human,
    { id: "upload-task", type: "ai", content: "Uploading files" },
  ]);
  expect(
    mergeMessages([], [], getVisibleOptimisticMessages(failed, 0, 0)),
  ).toEqual([human]);
});

test("a failed run with a checkpoint human message does not duplicate its optimistic input", () => {
  const persisted: Message = { ...human, id: "server-human" };
  const visible = getVisibleOptimisticMessages(
    preserveFailedSubmission([human]),
    0,
    1,
  );
  expect(visible).toEqual([]);
  expect(mergeMessages([], [persisted], visible)).toEqual([persisted]);
});

test("restored edited text keeps uploaded files and includes any newly attached files", () => {
  const extraFile = {
    filename: "notes.txt",
    size: 8,
    path: "/uploads/notes.txt",
    status: "uploaded" as const,
  };
  const [restored] = buildThreadSubmitMessages({
    text: "Summarize my report instead",
    additionalKwargs: human.additional_kwargs,
    filesForSubmit: [extraFile],
  });
  expect(restored?.content).toEqual([
    { type: "text", text: "Summarize my report instead" },
  ]);
  expect(restored?.additional_kwargs?.files).toEqual([uploadedFile, extraFile]);
});

test("validation exceptions are mapped to fixed actionable copy without disclosing model configuration", () => {
  const raw =
    "1 validation error for CodexChatModel: Codex CLI credential not found. input_value={'api_key':'sensitive-test-value'} Traceback";
  const kind = classifySubmissionError(new Error(raw));
  expect(kind).toBe("authentication");
  expect(enUS.conversation.submissionErrors[kind]).toContain("credentials");
  expect(enUS.conversation.submissionErrors[kind]).not.toContain(
    "sensitive-test-value",
  );
  expect(
    classifySubmissionError({ message: "An unexpected config dump" }),
  ).toBe("unknown");
  expect(classifySubmissionError({ status: 429 })).toBe("rateLimit");
  expect(classifySubmissionError(new Error("Failed to fetch"))).toBe(
    "connection",
  );
});

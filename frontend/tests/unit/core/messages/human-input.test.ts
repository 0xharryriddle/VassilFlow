import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "@rstest/core";

import {
  buildHumanInputResponseText,
  createHumanInputOptionResponse,
  deriveHumanInputThreadState,
  extractHumanInputRequest,
  parseHumanInputRequest,
  parseHumanInputResponse,
  shouldClearPendingHumanInputOnThreadError,
} from "@/core/messages/human-input";
import { isHiddenFromUIMessage } from "@/core/messages/utils";

const requestPayload = {
  version: 1,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-abc",
  tool_call_id: "call-abc",
  clarification_type: "approach_choice",
  question: "Which environment?",
  context: "Need a deploy target.",
  input_mode: "choice_with_other",
  options: [
    { id: "option-1", label: "development", value: "development" },
    { id: "option-2", label: "staging", value: "staging" },
  ],
} as const;

test("parseHumanInputRequest accepts structured clarification payload", () => {
  expect(parseHumanInputRequest(requestPayload)).toEqual(requestPayload);
});

test("parseHumanInputRequest rejects choice payload without options", () => {
  expect(
    parseHumanInputRequest({
      ...requestPayload,
      options: [],
    }),
  ).toBeNull();
});

test("extractHumanInputRequest reads tool artifact", () => {
  const message = {
    type: "tool",
    name: "ask_clarification",
    content: "Which environment?",
    artifact: { human_input: requestPayload },
  } as unknown as Message;

  expect(extractHumanInputRequest(message)).toEqual(requestPayload);
});

test("parseHumanInputResponse rejects empty hidden response values", () => {
  expect(
    parseHumanInputResponse({
      version: 1,
      kind: "human_input_response",
      source: "ask_clarification",
      request_id: "clarification:call-abc",
      response_kind: "text",
      value: "",
    }),
  ).toBeNull();
});

test("deriveHumanInputThreadState matches hidden response to visible request", () => {
  const requestMessage = {
    type: "tool",
    name: "ask_clarification",
    content: "Which environment?",
    artifact: { human_input: requestPayload },
  } as unknown as Message;
  const responseMessage = {
    type: "human",
    content: "For your clarification, my answer is: staging",
    additional_kwargs: {
      hide_from_ui: true,
      human_input_response: {
        version: 1,
        kind: "human_input_response",
        source: "ask_clarification",
        request_id: "clarification:call-abc",
        response_kind: "option",
        option_id: "option-2",
        value: "staging",
      },
    },
  } as Message;

  const state = deriveHumanInputThreadState(
    [requestMessage, responseMessage],
    (message) => !isHiddenFromUIMessage(message),
  );

  expect(state.latestOpenRequestId).toBeNull();
  expect(state.answeredResponses.get("clarification:call-abc")).toEqual(
    responseMessage.additional_kwargs?.human_input_response,
  );
});

test("createHumanInputOptionResponse and text fallback preserve answer", () => {
  const request = parseHumanInputRequest(requestPayload)!;
  const response = createHumanInputOptionResponse(
    request,
    request.options![1]!,
  );

  expect(response.value).toBe("staging");
  expect(buildHumanInputResponseText(request, response)).toBe(
    'For your clarification "Which environment?", my answer is: staging',
  );
});

test("shouldClearPendingHumanInputOnThreadError only reacts to new errors", () => {
  const error = new Error("stream failed");

  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError: error,
      previousError: null,
      pendingRequestCount: 1,
    }),
  ).toBe(true);
  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError: error,
      previousError: error,
      pendingRequestCount: 1,
    }),
  ).toBe(false);
  expect(
    shouldClearPendingHumanInputOnThreadError({
      currentError: error,
      previousError: null,
      pendingRequestCount: 0,
    }),
  ).toBe(false);
});

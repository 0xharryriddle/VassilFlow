import { expect, test, type Page } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_SIDECAR_THREAD_ID,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const SIDECAR_METADATA_KEY = "vassilflow_sidecar";

function threadWithAssistantQuote(quote: string) {
  return {
    thread_id: MOCK_THREAD_ID,
    title: "Quoted follow-up conversation",
    updated_at: "2025-06-05T12:00:00Z",
    messages: [
      {
        type: "human",
        id: "msg-human-sidecar",
        content: [{ type: "text", text: "Give me a reusable note" }],
      },
      {
        type: "ai",
        id: "msg-ai-sidecar",
        content: `This answer contains ${quote} for follow-up testing.`,
      },
    ],
  };
}

async function selectVisibleText(
  page: Page,
  text: string,
  scopeTestId?: string,
) {
  const scope = scopeTestId ? page.getByTestId(scopeTestId) : page;
  await scope.getByText(text).first().scrollIntoViewIfNeeded();
  await page.evaluate(
    ({ targetText, testId }) => {
      const root = testId
        ? document.querySelector(`[data-testid="${testId}"]`)
        : document.body;
      if (!root) {
        throw new Error(`Could not find selection scope ${testId}`);
      }
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node: Text | null = null;
      while (walker.nextNode()) {
        const current = walker.currentNode as Text;
        if (current.nodeValue?.includes(targetText)) {
          node = current;
          break;
        }
      }
      if (!node?.nodeValue) {
        throw new Error(`Could not find text node for ${targetText}`);
      }

      const start = node.nodeValue.indexOf(targetText);
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, start + targetText.length);

      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);

      const rect = range.getBoundingClientRect();
      node.parentElement?.dispatchEvent(
        new MouseEvent("mouseup", {
          bubbles: true,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2,
        }),
      );
    },
    { targetText: text, testId: scopeTestId },
  );
  await expect(page.locator("[data-sidecar-selection-toolbar]")).toBeVisible();
}

async function selectionToolbarLabels(page: Page) {
  return page
    .locator("[data-sidecar-selection-toolbar] button")
    .evaluateAll((buttons) =>
      buttons.map((button) => button.textContent?.trim() ?? ""),
    );
}

function inputMessages(body: unknown) {
  if (typeof body !== "object" || body === null) {
    return [];
  }
  const input = Reflect.get(body, "input");
  if (typeof input !== "object" || input === null) {
    return [];
  }
  const messages = Reflect.get(input, "messages");
  return Array.isArray(messages) ? messages : [];
}

function messageText(message: unknown) {
  if (typeof message !== "object" || message === null) {
    return "";
  }
  const content = Reflect.get(message, "content");
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((part) => {
      if (typeof part !== "object" || part === null) {
        return "";
      }
      const text = Reflect.get(part, "text");
      return typeof text === "string" ? text : "";
    })
    .join("");
}

function additionalKwargs(message: unknown) {
  if (typeof message !== "object" || message === null) {
    return {};
  }
  const value = Reflect.get(message, "additional_kwargs");
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

test.describe("Side conversations", () => {
  test.describe.configure({ timeout: 60_000 });

  test("adds selected assistant text as a quoted context for the main chat", async ({
    page,
  }) => {
    const quote = "MAINQUOTE";
    mockLangGraphAPI(page, { threads: [threadWithAssistantQuote(quote)] });

    let streamBody: unknown;
    await page.route(
      `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/stream`,
      (route) => {
        streamBody = route.request().postDataJSON();
        return handleRunStream(route);
      },
    );

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(quote)).toBeVisible({ timeout: 15_000 });

    await selectVisibleText(page, quote);
    await page.getByRole("button", { name: "Add to conversation" }).click();
    await expect(
      page.getByTestId("conversation-quote-attachment"),
    ).toBeVisible();

    const textarea = page.locator("textarea[name='message']").first();
    await textarea.fill("Use the quoted fragment in the next answer");
    await textarea.press("Enter");

    await expect.poll(() => streamBody).toBeDefined();
    const messages = inputMessages(streamBody);
    expect(
      messages.some((message) => {
        const kwargs = additionalKwargs(message);
        return (
          kwargs.hide_from_ui === true &&
          kwargs.conversation_quote_context === true &&
          messageText(message).includes(quote)
        );
      }),
    ).toBe(true);
    expect(
      messages.some((message) => {
        const kwargs = additionalKwargs(message);
        return (
          kwargs.referenced_message_count === 1 &&
          messageText(message).includes("Use the quoted fragment")
        );
      }),
    ).toBe(true);

    await expect(
      page.getByText("The user added the following quoted context"),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("message-reference-attachment").first(),
    ).toBeVisible();
  });

  test("creates a VassilFlow side chat from selected assistant text", async ({
    page,
  }) => {
    const quote = "SIDECARQUOTE";
    mockLangGraphAPI(page, { threads: [threadWithAssistantQuote(quote)] });

    let createSidecarPayload: Record<string, unknown> | undefined;
    const streamBodies: unknown[] = [];

    await page.route("**/api/threads", (route) => {
      if (route.request().method() === "POST") {
        createSidecarPayload = route.request().postDataJSON() as Record<
          string,
          unknown
        >;
      }
      return route.fallback();
    });
    await page.route("**/api/langgraph/threads/*/runs/stream", (route) => {
      streamBodies.push(route.request().postDataJSON());
      return handleRunStream(route);
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(quote)).toBeVisible({ timeout: 15_000 });

    await selectVisibleText(page, quote);
    await page.getByRole("button", { name: "Ask in side chat" }).click();

    const sidecarPanel = page.getByTestId("sidecar-panel");
    await expect(sidecarPanel).toBeVisible();
    await expect(
      sidecarPanel.getByTestId("sidecar-reference-attachment"),
    ).toBeVisible();

    const sidecarTextarea = sidecarPanel.locator("textarea[name='message']");
    await expect(sidecarTextarea).toBeEnabled();
    await sidecarTextarea.fill("Explain this quoted fragment");
    await sidecarTextarea.press("Enter");

    await expect.poll(() => createSidecarPayload).toBeDefined();
    const metadata = createSidecarPayload?.metadata as
      | Record<string, unknown>
      | undefined;
    expect(metadata).toMatchObject({
      [SIDECAR_METADATA_KEY]: true,
      parent_thread_id: MOCK_THREAD_ID,
      referenced_message_ids: ["msg-ai-sidecar"],
    });

    await expect.poll(() => streamBodies.length).toBeGreaterThan(0);
    const sidecarMessages = inputMessages(streamBodies.at(-1));
    expect(
      sidecarMessages.some((message) => {
        const kwargs = additionalKwargs(message);
        return (
          kwargs.hide_from_ui === true &&
          kwargs.sidecar_context === true &&
          messageText(message).includes(quote)
        );
      }),
    ).toBe(true);
    expect(
      sidecarMessages.some((message) =>
        messageText(message).includes("Explain this quoted fragment"),
      ),
    ).toBe(true);

    await expect(
      sidecarPanel.getByText("Hello from VassilFlow!"),
    ).toBeVisible();
    await selectVisibleText(page, "VassilFlow", "sidecar-panel");
    const labels = await selectionToolbarLabels(page);
    expect(labels.some((label) => /add to conversation/i.test(label))).toBe(
      true,
    );
    expect(labels.some((label) => /ask in side chat/i.test(label))).toBe(false);
    await page.getByRole("button", { name: "Add to conversation" }).click();
    await expect(
      sidecarPanel.getByTestId("sidecar-reference-attachment"),
    ).toBeVisible();
    await expect(
      page.locator("form").first().getByTestId("conversation-quote-attachment"),
    ).toHaveCount(0);

    await sidecarPanel.getByTestId("sidecar-delete-button").click();
    await expect(page.getByRole("dialog")).toContainText("Delete side chat");
    await page.getByTestId("sidecar-delete-confirm-button").click();
    await expect(sidecarPanel).toBeHidden();
    await expect(page.getByTestId("sidecar-header-trigger")).toHaveCount(0);
    await expect(
      page.locator(`a[href='/workspace/chats/${MOCK_SIDECAR_THREAD_ID}']`),
    ).toHaveCount(0);
  });
});

import { expect, test } from "@playwright/test";

import { handleRunStreamValues, mockLangGraphAPI } from "./utils/mock-api";

test("completed reasoning keeps its measured time without changing control mode", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  const warnings: string[] = [];
  page.on("console", (message) => {
    if (/changing from (uncontrolled|controlled) to/.test(message.text())) {
      warnings.push(message.text());
    }
  });
  await page.route("**/runs/stream", async (route) => {
    // Give the turn a non-zero duration before delivering a complete reply.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    return handleRunStreamValues(route, [
      { id: "human-reasoning", type: "human", content: "Explain briefly" },
      {
        id: "ai-reasoning",
        type: "ai",
        content: "A complete reply.",
        additional_kwargs: { reasoning_content: "I considered the question." },
      },
    ]);
  });

  await page.goto("/workspace/chats/new");
  const textarea = page.getByPlaceholder(/how can i assist you/i);
  await expect(textarea).toBeVisible();
  await textarea.fill("Explain briefly");
  await textarea.press("Enter");

  await expect(page.getByText("A complete reply.")).toBeVisible();
  const reasoning = page.getByRole("button", {
    name: /Thought for \d+ seconds/,
  });
  await expect(reasoning).toBeVisible();
  const measuredLabel = await reasoning.textContent();
  await expect(reasoning).toHaveAttribute("aria-expanded", "false");
  await reasoning.click();
  await expect(reasoning).toHaveAttribute("aria-expanded", "true");
  await expect(reasoning).toHaveText(measuredLabel!);
  expect(warnings).toEqual([]);
});

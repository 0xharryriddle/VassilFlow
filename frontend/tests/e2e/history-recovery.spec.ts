import { expect, test } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

const threads = [
  { thread_id: MOCK_THREAD_ID, title: "History recovery first" },
  { thread_id: MOCK_THREAD_ID_2, title: "History recovery second" },
];
const messagesPattern = /\/api\/threads\/[^/]+\/runs\/[^/]+\/messages/;

test("history HTTP errors keep the conversation and allow an explicit retry", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads });
  let requests = 0;
  let fail = true;
  await page.route(messagesPattern, (route) => {
    requests += 1;
    return route.fulfill({
      status: fail ? 500 : 200,
      contentType: "application/json",
      body: JSON.stringify(
        fail
          ? { data: [], detail: "private-server-traceback" }
          : {
              data: [
                {
                  run_id: `run-${MOCK_THREAD_ID}`,
                  content: {
                    id: "restored-history",
                    type: "ai",
                    content: "Recovered earlier history",
                  },
                  metadata: {},
                  created_at: "2024-01-01T00:00:00Z",
                },
              ],
              has_more: false,
            },
      ),
    });
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  const retry = page.getByRole("button", { name: "Retry history" });
  await expect(retry).toBeVisible({ timeout: 15_000 });
  await expect(
    page.getByText("Response in thread History recovery first"),
  ).toBeVisible();
  await expect(page.getByText("private-server-traceback")).toHaveCount(0);
  // The visible scroll sentinel must not keep hammering a failed endpoint.
  const failedRequests = requests;
  await page.waitForTimeout(1600);
  expect(requests).toBe(failedRequests);
  fail = false;
  await retry.click();
  await expect(page.getByText("Recovered earlier history")).toBeVisible();
  await expect(retry).toBeHidden();
});

test("a failed runs list exposes the same retry control", async ({ page }) => {
  mockLangGraphAPI(page, { threads });
  let fail = true;
  await page.route(/\/api\/langgraph\/threads\/[^/]+\/runs(\?|$)/, (route) =>
    fail
      ? route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "unavailable" }),
        })
      : route.fallback(),
  );
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  const retry = page.getByRole("button", { name: "Retry history" });
  await expect(retry).toBeVisible({ timeout: 30_000 });
  fail = false;
  await retry.click();
  await expect(retry).toBeHidden();
  await expect(
    page.getByText("Response in thread History recovery first"),
  ).toBeVisible();
});

test("switching threads discards a delayed history failure from the previous thread", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested = false;
  await page.route(messagesPattern, async (route) => {
    if (!route.request().url().includes(MOCK_THREAD_ID))
      return route.fallback();
    requested = true;
    await gate;
    await route
      .fulfill({ status: 500, contentType: "application/json", body: "{}" })
      .catch(() => undefined);
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect.poll(() => requested).toBe(true);
  await page.getByRole("link", { name: "History recovery second" }).click();
  await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID_2));
  release();
  await expect(
    page.getByText("Response in thread History recovery second"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry history" }),
  ).toBeHidden();
  await expect(
    page.getByText("Response in thread History recovery first"),
  ).toHaveCount(0);
});

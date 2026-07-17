import { expect, test } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_THREAD_ID,
} from "./utils/mock-api";

const MOCK_AGENTS = [
  {
    name: "test-agent",
    description: "A test agent for E2E tests",
    system_prompt: "You are a test agent.",
  },
];

const MOCK_OFFICE_AGENT = {
  name: "office",
  description:
    "Inspect, revise, render, and review Word, Excel, and PowerPoint files.",
  model: null,
  tool_groups: ["file:read", "file:write"],
  skills: [],
  product: {
    id: "builtin:office",
    display_name: "Office",
    origin: "builtin",
    category: "create",
    icon: "files",
    status: "available",
    required_tools: ["office_inspect", "office_edit", "office_render"],
    missing_requirements: [],
    data_access: ["thread_uploads", "thread_workspace", "thread_outputs"],
    starter_prompts: [
      "Inspect an uploaded Office file and summarize its structure.",
    ],
    launch: {
      kind: "chat",
      path: "/workspace/agents/office/chats/new",
      project_kind: null,
    },
    management: { can_edit: false, can_delete: false },
  },
};

test.describe("Agent chat", () => {
  test("agent gallery page loads and shows agents", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents");

    // The agent card should appear with the agent name
    await expect(page.getByText("test-agent")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("built-in catalog works when custom Agent management is disabled", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: [MOCK_OFFICE_AGENT],
      customAgentManagementEnabled: false,
    });

    await page.goto("/workspace/agents");

    await expect(
      page.getByLabel("All agents").getByText("Office", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New Agent" })).toBeHidden();
    await page.getByRole("button", { name: "View Office details" }).click();
    await expect(page.getByRole("heading", { name: "Office" })).toBeVisible();
  });

  test("personal Agent runtime remains launchable when management is disabled", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      customAgentManagementEnabled: false,
    });

    await page.goto("/workspace/agents/test-agent/chats/new");

    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("button", { name: "New Agent" })).toBeHidden();
  });

  test("agent catalog searches and persists pinned shortcuts", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, {
      agents: [
        ...MOCK_AGENTS,
        {
          name: "research-agent",
          description: "Collects traceable sources",
        },
      ],
    });

    await page.goto("/workspace/agents");
    const search = page.getByRole("searchbox", { name: "Search agents" });
    await search.fill("traceable");
    await expect(page.getByText("research-agent")).toBeVisible();
    await expect(page.getByText("test-agent")).toBeHidden();

    await search.clear();
    await page.getByRole("button", { name: "Pin test-agent" }).click();
    await expect(page.getByRole("heading", { name: "Pinned" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Unpin test-agent" }),
    ).toBeVisible();
    await expect(
      page
        .locator('[data-sidebar="content"]')
        .getByRole("link", { name: "test-agent" }),
    ).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() =>
          localStorage.getItem("vassilflow.agents.pinned.default"),
        ),
      )
      .toContain("personal:test-agent");

    await page.reload();
    await expect(
      page.getByRole("button", { name: "Unpin test-agent" }),
    ).toBeVisible();
    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("agent-catalog-desktop.png"),
        fullPage: true,
      });
    }
  });

  test("agent catalog filters categories and opens the Office profile", async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, {
      agents: [MOCK_OFFICE_AGENT, ...MOCK_AGENTS],
    });

    await page.goto("/workspace/agents");
    await page.getByRole("combobox", { name: "All categories" }).click();
    await page.getByRole("option", { name: "Create" }).click();

    await expect(
      page.getByLabel("All agents").getByText("Office", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("test-agent", { exact: true })).toBeHidden();

    await page.getByRole("button", { name: "View Office details" }).click();
    await expect(page.getByRole("heading", { name: "Office" })).toBeVisible();
    await expect(
      page.getByText("office_render", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Inspect an uploaded Office file and summarize its structure.",
      ),
    ).toBeVisible();
    await page.getByRole("button", { name: "Pin Office" }).click();

    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("agent-office-profile.png"),
        fullPage: true,
      });
    }

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    const officeAgentShortcut = page.locator(
      '[data-sidebar="content"] a[href="/workspace/agents/office/chats/new"]',
    );
    await expect(officeAgentShortcut).toBeVisible();
    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("agent-office-catalog-pinned.png"),
        fullPage: true,
      });
    }

    await page.locator('[data-sidebar="trigger"]').click();
    await expect(page.locator('[data-slot="sidebar"]')).toHaveAttribute(
      "data-state",
      "collapsed",
    );
    const collapsedOfficeShortcut = officeAgentShortcut;
    await expect(collapsedOfficeShortcut).toBeVisible();
    await collapsedOfficeShortcut.hover();
    await expect(page.getByRole("tooltip", { name: "Office" })).toBeVisible();
    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("agent-office-sidebar-collapsed.png"),
        fullPage: true,
      });
    }

    await page.getByRole("button", { name: "View Office details" }).click();
    await page.getByRole("button", { name: "Chat", exact: true }).click();
    await expect(page).toHaveURL(/\/workspace\/agents\/office\/chats\/new$/);
  });

  test("agent catalog remains usable without horizontal overflow on mobile", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      agents: [
        MOCK_OFFICE_AGENT,
        ...MOCK_AGENTS,
        {
          name: "research-agent",
          description: "Collects traceable sources",
        },
        {
          name: "proposal-agent",
          description: "Builds account proposals",
        },
      ],
    });

    await page.goto("/workspace/agents");
    await expect(
      page.getByRole("searchbox", { name: "Search agents" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "New Agent" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Pin test-agent" }),
    ).toBeVisible();

    const viewport = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);

    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await page.screenshot({
        path: testInfo.outputPath("agent-catalog-mobile.png"),
        fullPage: true,
      });
    }

    await page.getByRole("button", { name: "View Office details" }).click();
    const profile = page.getByRole("dialog");
    await expect(
      profile.getByRole("heading", { name: "Office" }),
    ).toBeVisible();
    const profileBox = await profile.boundingBox();
    expect(profileBox).not.toBeNull();
    expect(profileBox!.width).toBeLessThanOrEqual(390);

    if (process.env.CAPTURE_AGENT_CATALOG_SCREENSHOTS === "1") {
      await profile.screenshot({
        path: testInfo.outputPath("agent-office-profile-mobile.png"),
      });
    }
  });

  test("agent chat page loads with input box", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents/test-agent/chats/new");

    // The prompt input textarea should be visible
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
  });

  test("agent chat page shows agent badge", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });

    await page.goto("/workspace/agents/test-agent/chats/new");

    // The agent badge should display in the header (scoped to header to avoid
    // matching the welcome area which also shows the agent name)
    await expect(
      page.locator("header span", { hasText: "test-agent" }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("thread identity redirects a mismatched Agent route", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          assistant_id: "lead_agent",
          title: "Default Agent thread",
        },
      ],
    });

    await page.goto(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}`);

    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID}$`),
    );
  });

  test("legacy Agent thread remains reachable for server migration", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          assistant_id: "lead_agent",
          metadata: { agent_name: "test-agent" },
          title: "Legacy Agent thread",
        },
      ],
    });

    await page.goto(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}`);

    await expect(page).toHaveURL(
      new RegExp(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}$`),
    );
  });

  test("agent chat submits the canonical assistant id", async ({ page }) => {
    mockLangGraphAPI(page, { agents: MOCK_AGENTS });
    let streamBody: Record<string, unknown> | undefined;
    await page.route(
      /\/api\/langgraph\/(?:threads\/[^/]+\/)?runs\/stream(?:\?|$)/,
      (route) => {
        streamBody = route.request().postDataJSON() as Record<string, unknown>;
        return handleRunStream(route);
      },
    );

    await page.goto("/workspace/agents/test-agent/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Confirm the Agent contract");
    await textarea.press("Enter");

    await expect.poll(() => streamBody).toBeDefined();
    expect(streamBody?.assistant_id).toBe("test-agent");
    expect(
      (streamBody?.context as Record<string, unknown> | undefined)?.agent_name,
    ).toBeUndefined();
  });

  test("agent chat can regenerate its latest response", async ({ page }) => {
    const humanMessage = {
      type: "human",
      id: "msg-human-agent",
      content: [{ type: "text", text: "Original agent question" }],
    };
    const aiMessage = {
      type: "ai",
      id: "msg-ai-agent",
      content: "Custom agent response",
    };
    mockLangGraphAPI(page, {
      agents: MOCK_AGENTS,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Agent conversation",
          agent_name: "test-agent",
          messages: [humanMessage, aiMessage],
        },
      ],
    });

    let prepareMessageId: string | undefined;
    let streamBody: Record<string, unknown> | undefined;
    await page.route(
      `**/api/threads/${MOCK_THREAD_ID}/runs/regenerate/prepare`,
      (route) => {
        prepareMessageId = (
          route.request().postDataJSON() as { message_id?: string }
        ).message_id;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            input: { messages: [humanMessage] },
            checkpoint: {
              checkpoint_id: "checkpoint-before-human",
              checkpoint_ns: "",
              checkpoint_map: null,
            },
            metadata: {
              regenerate_from_message_id: aiMessage.id,
              regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
              regenerate_checkpoint_id: "checkpoint-before-human",
            },
            target_run_id: `run-${MOCK_THREAD_ID}`,
          }),
        });
      },
    );
    await page.route(
      `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/stream`,
      (route) => {
        streamBody = route.request().postDataJSON() as Record<string, unknown>;
        return handleRunStream(route);
      },
    );

    await page.goto(`/workspace/agents/test-agent/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(aiMessage.content)).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: "Regenerate" }).click();

    await expect.poll(() => prepareMessageId).toBe(aiMessage.id);
    await expect.poll(() => streamBody).toBeDefined();
    expect(streamBody).toMatchObject({
      assistant_id: "test-agent",
      checkpoint: {
        checkpoint_id: "checkpoint-before-human",
        checkpoint_ns: "",
        checkpoint_map: null,
      },
      metadata: {
        regenerate_from_message_id: aiMessage.id,
        regenerate_from_run_id: `run-${MOCK_THREAD_ID}`,
        regenerate_checkpoint_id: "checkpoint-before-human",
      },
      context: {
        thread_id: MOCK_THREAD_ID,
      },
    });
  });
});

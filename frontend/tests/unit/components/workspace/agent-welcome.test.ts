import { expect, rs, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      agents: {
        launchUnavailable: "This agent is unavailable",
        limitedAvailability: "Limited availability",
      },
    },
  }),
}));

import { AgentWelcome } from "@/components/workspace/agent-welcome";

test("missing agents explain the disabled composer after loading", () => {
  const html = renderToStaticMarkup(
    createElement(AgentWelcome, {
      agent: null,
      agentName: "missing-agent",
      isLoading: false,
    }),
  );
  expect(html).toContain("This agent is unavailable");
});

test("loading catalog entries do not prematurely show an unavailable error", () => {
  const html = renderToStaticMarkup(
    createElement(AgentWelcome, {
      agent: null,
      agentName: "loading-agent",
      isLoading: true,
    }),
  );
  expect(html).not.toContain("This agent is unavailable");
});

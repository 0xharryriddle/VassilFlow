import { describe, expect, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ReasoningTrigger,
  useReasoning,
} from "@/components/ai-elements/reasoning";
import { MessageReasoning } from "@/components/workspace/messages/message-reasoning";

function StartTimeProbe() {
  const { startTime } = useReasoning();
  return createElement("output", { "data-start-time": startTime ?? "none" });
}

describe("message reasoning duration", () => {
  test("renders the saved duration without restarting its timer", () => {
    const html = renderToStaticMarkup(
      createElement(
        MessageReasoning,
        {
          duration: 12,
          startTimeProp: 1000,
          isStreaming: false,
          defaultOpen: false,
        },
        createElement(ReasoningTrigger),
        createElement(StartTimeProbe),
      ),
    );

    expect(html).toContain("Thought for 12 seconds");
    expect(html).toContain('data-start-time="none"');
    expect(html).toContain('aria-expanded="false"');
  });

  test("keeps the run start time while the duration is still being measured", () => {
    const html = renderToStaticMarkup(
      createElement(
        MessageReasoning,
        { startTimeProp: 1000, isStreaming: true },
        createElement(ReasoningTrigger),
        createElement(StartTimeProbe),
      ),
    );

    expect(html).toContain("Thinking...");
    expect(html).toContain('data-start-time="1000"');
  });

  test("does not invent a duration for historical messages without timing", () => {
    const html = renderToStaticMarkup(
      createElement(MessageReasoning, {}, createElement(ReasoningTrigger)),
    );
    expect(html).toContain("Thought for a few seconds");
  });
});

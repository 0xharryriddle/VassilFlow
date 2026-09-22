import type { LocalSettings } from "@/core/settings/local";

/** Resolve the effort already sent by the thread submission transport. */
export function resolveReasoningEffort(
  context: Pick<LocalSettings["context"], "mode" | "reasoning_effort">,
) {
  return (
    context.reasoning_effort ??
    (context.mode === "ultra"
      ? "high"
      : context.mode === "pro"
        ? "medium"
        : context.mode === "thinking"
          ? "low"
          : undefined)
  );
}

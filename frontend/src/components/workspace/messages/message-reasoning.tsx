"use client";

import { useCallback, useState } from "react";

import {
  Reasoning,
  type ReasoningProps,
} from "@/components/ai-elements/reasoning";

type MessageReasoningProps = Omit<ReasoningProps, "onOpenChange"> & {
  onOpenChange?: (open: boolean) => void;
};

export function MessageReasoning({
  duration,
  open,
  defaultOpen = true,
  onOpenChange,
  isStreaming = false,
  startTimeProp,
  ...props
}: MessageReasoningProps) {
  // Keep expansion outside the measured/unmeasured Reasoning instances so a
  // completed duration never reopens a panel the user has collapsed.
  const [expanded, setExpanded] = useState(defaultOpen);
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      setExpanded(nextOpen);
      onOpenChange?.(nextOpen);
    },
    [onOpenChange],
  );

  return (
    <Reasoning
      {...props}
      // A duration starts unknown and is stored after streaming. Give the
      // measured phase its own instance instead of changing Radix control mode.
      key={duration === undefined ? "measuring" : "measured"}
      duration={duration}
      isStreaming={isStreaming}
      startTimeProp={
        isStreaming || duration === undefined ? startTimeProp : null
      }
      defaultOpen={defaultOpen}
      open={open ?? expanded}
      onOpenChange={handleOpenChange}
    />
  );
}

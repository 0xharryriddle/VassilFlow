"use client";

import { MessageSquareTextIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { Tooltip } from "../tooltip";

import { useMaybeSidecar } from "./context";

export function SidecarTrigger() {
  const { t } = useI18n();
  const sidecar = useMaybeSidecar();
  const [isReconciling, setIsReconciling] = useState(false);

  if (!sidecar?.sidecarThreadId) {
    return null;
  }

  const label = sidecar.open ? t.sidecar.close : t.sidecar.open;

  const handleClick = async () => {
    if (sidecar.open) {
      sidecar.close();
      return;
    }
    setIsReconciling(true);
    try {
      const restoredThreadId = await sidecar.restoreSidecarThread({
        force: true,
      });
      if (restoredThreadId) {
        sidecar.openSidecar();
      }
    } finally {
      setIsReconciling(false);
    }
  };

  return (
    <Tooltip content={label}>
      <Button
        aria-label={label}
        className="text-muted-foreground hover:text-foreground"
        data-testid="sidecar-header-trigger"
        disabled={isReconciling}
        size="icon"
        type="button"
        variant={sidecar.open ? "secondary" : "ghost"}
        onClick={() => {
          void handleClick();
        }}
      >
        <MessageSquareTextIcon />
      </Button>
    </Tooltip>
  );
}

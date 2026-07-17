import { BotIcon, FilesIcon } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function iconForAgent(icon: string): LucideIcon {
  return icon === "files" ? FilesIcon : BotIcon;
}

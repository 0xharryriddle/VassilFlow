"use client";

import {
  ChevronDownIcon,
  FileTextIcon,
  PlusIcon,
  PresentationIcon,
  SheetIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";

export function OfficeNewMenu() {
  const { t } = useI18n();
  const options = [
    {
      id: "presentation",
      label: t.office.newPresentation,
      icon: PresentationIcon,
    },
    { id: "document", label: t.office.newDocument, icon: FileTextIcon },
    { id: "workbook", label: t.office.newWorkbook, icon: SheetIcon },
  ] as const;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button>
          <PlusIcon />
          {t.office.new}
          <ChevronDownIcon className="size-3.5 opacity-70" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-44">
        {options.map(({ id, label, icon: Icon }) => (
          <DropdownMenuItem key={id} asChild>
            <Link href={`/workspace/agents/office/chats/new?starter=${id}`}>
              <Icon />
              {label}
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

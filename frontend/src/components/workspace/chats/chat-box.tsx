import { FilesIcon, XIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GroupImperativeHandle } from "react-resizable-panels";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { env } from "@/env";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import { useThread } from "../messages/context";
import { SidecarPanel, useMaybeSidecar } from "../sidecar";

const CLOSE_MODE = { chat: 100, artifacts: 0 };
const OPEN_MODE = { chat: 60, artifacts: 40 };

type RightPanelKind = "sidecar" | "artifacts";

const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
  const { thread } = useThread();
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);
  const layoutRef = useRef<GroupImperativeHandle>(null);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    deselect,
    selectedArtifact,
  } = useArtifacts();
  const sidecar = useMaybeSidecar();
  const sidecarOpen = sidecar?.open ?? false;

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  useEffect(() => {
    const threadArtifacts = Array.isArray(thread.values.artifacts)
      ? thread.values.artifacts
      : [];

    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setArtifacts([]);
    }

    // Update artifacts from the current thread
    setArtifacts(threadArtifacts);

    // DO NOT automatically deselect the artifact when switching threads, because the artifacts auto discovering is not work now.
    // if (
    //   selectedArtifact &&
    //   !thread.values.artifacts?.includes(selectedArtifact)
    // ) {
    //   deselect();
    // }

    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (threadArtifacts.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(threadArtifacts[0]!);
      }
    }
  }, [
    threadId,
    autoSelectFirstArtifact,
    deselect,
    selectArtifact,
    selectedArtifact,
    setArtifacts,
    thread.values.artifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (sidecarOpen) {
      return false;
    }
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts, sidecarOpen]);

  const activeRightPanel: RightPanelKind | null = sidecarOpen
    ? "sidecar"
    : artifactPanelOpen
      ? "artifacts"
      : null;
  const rightPanelOpen = activeRightPanel !== null;

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  useEffect(() => {
    if (layoutRef.current) {
      if (rightPanelOpen) {
        layoutRef.current.setLayout(OPEN_MODE);
      } else {
        layoutRef.current.setLayout(CLOSE_MODE);
      }
    }
  }, [rightPanelOpen]);

  useEffect(() => {
    if (sidecarOpen && artifactsOpen) {
      setArtifactsOpen(false);
    }
  }, [artifactsOpen, setArtifactsOpen, sidecarOpen]);

  const artifactPanelContent = useMemo(() => {
    if (selectedArtifact) {
      return (
        <ArtifactFileDetail
          className="size-full"
          filepath={selectedArtifact}
          threadId={threadId}
        />
      );
    }

    return (
      <div className="relative flex size-full justify-center">
        <div className="absolute top-1 right-1 z-30">
          <Button
            aria-label="Close artifacts"
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              setArtifactsOpen(false);
            }}
          >
            <XIcon />
          </Button>
        </div>
        {artifacts.length === 0 ? (
          <ConversationEmptyState
            icon={<FilesIcon />}
            title="No artifact selected"
            description="Select an artifact to view its details"
          />
        ) : (
          <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
            <header className="shrink-0">
              <h2 className="text-lg font-medium">Artifacts</h2>
            </header>
            <main className="min-h-0 grow">
              <ArtifactFileList
                className="max-w-(--container-width-sm) p-4 pt-12"
                files={artifacts}
                threadId={threadId}
              />
            </main>
          </div>
        )}
      </div>
    );
  }, [artifacts, selectedArtifact, setArtifactsOpen, threadId]);

  const rightPanelContent = useMemo(() => {
    if (activeRightPanel === "sidecar") {
      return <SidecarPanel />;
    }
    if (activeRightPanel === "artifacts") {
      return artifactPanelContent;
    }
    return null;
  }, [activeRightPanel, artifactPanelContent]);

  if (isMobile) {
    return (
      <>
        <div className="relative size-full min-w-0">{children}</div>
        <Sheet
          open={rightPanelOpen}
          onOpenChange={(open) => {
            if (open) {
              return;
            }
            if (sidecarOpen) {
              sidecar?.close();
            }
            if (artifactsOpen) {
              setArtifactsOpen(false);
            }
          }}
        >
          <SheetContent
            className="w-[calc(100vw-1rem)] max-w-none gap-0 p-0 sm:max-w-md [&>button]:hidden"
            side="right"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>
                {activeRightPanel === "sidecar" ? "Side chat" : "Artifacts"}
              </SheetTitle>
              <SheetDescription>
                Browse the side panel for this conversation.
              </SheetDescription>
            </SheetHeader>
            <div
              className={cn(
                "min-h-0 flex-1 pt-10",
                activeRightPanel === "sidecar" ? "p-0" : "p-3",
              )}
            >
              {rightPanelContent}
            </div>
          </SheetContent>
        </Sheet>
      </>
    );
  }

  return (
    <ResizablePanelGroup
      id={`${resizableIdBase}-panels`}
      orientation="horizontal"
      defaultLayout={{ chat: 100, artifacts: 0 }}
      groupRef={layoutRef}
    >
      <ResizablePanel className="relative" defaultSize={100} id="chat">
        {children}
      </ResizablePanel>
      <ResizableHandle
        id={`${resizableIdBase}-separator`}
        className={cn(
          "opacity-33 hover:opacity-100",
          !rightPanelOpen && "pointer-events-none opacity-0",
        )}
      />
      <ResizablePanel
        className={cn(
          "transition-all duration-300 ease-in-out",
          !rightPanelOpen && "opacity-0",
        )}
        id="artifacts"
      >
        <div
          className={cn(
            "h-full p-4 transition-transform duration-300 ease-in-out",
            activeRightPanel === "sidecar" ? "p-0" : "p-4",
            rightPanelOpen ? "translate-x-0" : "translate-x-full",
          )}
        >
          {rightPanelContent}
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
};

export { ChatBox };

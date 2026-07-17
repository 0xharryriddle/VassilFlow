"use client";

import {
  CheckCircle2Icon,
  DownloadIcon,
  HistoryIcon,
  ImageIcon,
  LoaderCircleIcon,
  StarIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  officeFinalArtifactURL,
  type OfficeProjectDetail,
  type OfficeProjectReviewStatus,
  type OfficeRenderSet,
  type OfficeRevisionSummary,
  useRenderOfficeProjectRevision,
  useRestoreOfficeProjectRevision,
  useReviewOfficeProjectRevision,
  useSelectOfficeProjectFinal,
} from "@/core/office";
import { cn } from "@/lib/utils";

export function OfficeProjectActions({
  project,
  revision,
  renderSet,
  isCurrentRevision,
}: {
  project: OfficeProjectDetail;
  revision: OfficeRevisionSummary;
  renderSet: OfficeRenderSet;
  isCurrentRevision: boolean;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const renderMutation = useRenderOfficeProjectRevision();
  const reviewMutation = useReviewOfficeProjectRevision();
  const finalMutation = useSelectOfficeProjectFinal();
  const restoreMutation = useRestoreOfficeProjectRevision();
  const [reviewOpen, setReviewOpen] = useState(false);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [reviewStatus, setReviewStatus] =
    useState<OfficeProjectReviewStatus>("approved");
  const [reviewNote, setReviewNote] = useState("");

  const actionError = (error: unknown) =>
    toast.error(
      error instanceof Error ? error.message : t.office.reviewActionFailed,
    );

  const render = () => {
    renderMutation.mutate(
      { projectId: project.project_id, revisionId: revision.revision_id },
      {
        onSuccess: () => toast.success(t.office.renderComplete),
        onError: actionError,
      },
    );
  };

  const saveReview = () => {
    reviewMutation.mutate(
      {
        projectId: project.project_id,
        revisionId: revision.revision_id,
        evidenceIds: renderSet.evidence_ids,
        status: reviewStatus,
        note: reviewNote,
      },
      {
        onSuccess: () => {
          setReviewOpen(false);
          setReviewNote("");
          toast.success(
            reviewStatus === "approved"
              ? t.office.reviewApproved
              : t.office.reviewSaved,
          );
        },
        onError: actionError,
      },
    );
  };

  const selectFinal = () => {
    const review = revision.latest_review;
    if (review?.status !== "approved") return;
    finalMutation.mutate(
      {
        projectId: project.project_id,
        revisionId: revision.revision_id,
        reviewId: review.review_id,
        expectedCurrentRevisionId: project.current_revision.revision_id,
      },
      {
        onSuccess: () => toast.success(t.office.finalSelected),
        onError: actionError,
      },
    );
  };

  const restore = () => {
    restoreMutation.mutate(
      {
        projectId: project.project_id,
        targetRevisionId: revision.revision_id,
        expectedCurrentRevisionId: project.current_revision.revision_id,
      },
      {
        onSuccess: (result) => {
          setRestoreOpen(false);
          toast.success(t.office.restoreComplete);
          router.push(result.project_url);
        },
        onError: actionError,
      },
    );
  };

  return (
    <>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={render}
          disabled={renderMutation.isPending}
          aria-label={t.office.renderRevision}
        >
          {renderMutation.isPending ? (
            <LoaderCircleIcon className="animate-spin" />
          ) : (
            <ImageIcon />
          )}
          <span className="hidden xl:inline">
            {renderMutation.isPending
              ? t.office.renderingRevision
              : t.office.renderRevision}
          </span>
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={() => setReviewOpen(true)}
          disabled={!renderSet.complete}
          aria-label={t.office.approveRevision}
        >
          <CheckCircle2Icon />
          <span className="hidden xl:inline">{t.office.visualReview}</span>
        </Button>

        {revision.latest_review?.status === "approved" &&
          !revision.is_final && (
            <Button
              variant="outline"
              size="sm"
              onClick={selectFinal}
              disabled={finalMutation.isPending}
              aria-label={t.office.selectFinal}
            >
              {finalMutation.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <StarIcon />
              )}
              <span className="hidden xl:inline">
                {finalMutation.isPending
                  ? t.office.selectingFinal
                  : t.office.selectFinal}
              </span>
            </Button>
          )}

        {!isCurrentRevision && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setRestoreOpen(true)}
            disabled={restoreMutation.isPending}
            aria-label={t.office.restoreRevision(revision.sequence)}
          >
            <HistoryIcon />
            <span className="hidden xl:inline">{t.office.restore}</span>
          </Button>
        )}

        {project.final_selection && (
          <Button variant="outline" size="sm" asChild>
            <a
              href={officeFinalArtifactURL(project.project_id)}
              download
              aria-label={t.office.downloadFinal}
            >
              <DownloadIcon />
              <span className="hidden xl:inline">{t.office.downloadFinal}</span>
            </a>
          </Button>
        )}
      </div>

      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.office.visualReview}</DialogTitle>
            <DialogDescription>
              {t.office.pagesRendered(
                renderSet.rendered_page_count,
                renderSet.page_count,
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="bg-muted grid grid-cols-2 gap-1 rounded-md p-1">
            {(
              [
                ["approved", t.office.approveRevision],
                ["changes_requested", t.office.requestChanges],
              ] as const
            ).map(([status, label]) => (
              <button
                key={status}
                type="button"
                aria-pressed={reviewStatus === status}
                onClick={() => setReviewStatus(status)}
                className={cn(
                  "h-9 rounded-sm px-3 text-sm font-medium transition-colors",
                  reviewStatus === status
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="space-y-2 text-sm font-medium">
            <span>{t.office.reviewNote}</span>
            <Textarea
              value={reviewNote}
              onChange={(event) => setReviewNote(event.target.value)}
              maxLength={2048}
              placeholder={t.office.reviewNotePlaceholder}
              className="min-h-24 resize-y"
            />
          </label>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setReviewOpen(false)}
              disabled={reviewMutation.isPending}
            >
              {t.office.cancel}
            </Button>
            <Button onClick={saveReview} disabled={reviewMutation.isPending}>
              {reviewMutation.isPending && (
                <LoaderCircleIcon className="animate-spin" />
              )}
              {t.office.saveReview}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={restoreOpen} onOpenChange={setRestoreOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.office.restoreTitle}</DialogTitle>
            <DialogDescription>
              {t.office.restoreDescription(revision.sequence)}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRestoreOpen(false)}
              disabled={restoreMutation.isPending}
            >
              {t.office.cancel}
            </Button>
            <Button onClick={restore} disabled={restoreMutation.isPending}>
              {restoreMutation.isPending ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <HistoryIcon />
              )}
              {restoreMutation.isPending
                ? t.office.restoring
                : t.office.confirmRestore}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

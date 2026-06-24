"use client";
import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown, Send, Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { getZoneFromPath } from "@/lib/zones";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

interface FormulationRatingProps {
  conversationId: string;
  formulation: object; // snapshot of the rated formulation
}

export function FormulationRating({ conversationId, formulation }: FormulationRatingProps) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const t = useTranslations("common");

  const handleRate = useCallback(async (value: "up" | "down") => {
    setRating(value);
    setShowComment(true);
    setSubmitting(true);

    try {
      const zone = getZoneFromPath(window.location.pathname);
      await api.request(`/api/v2/feedback/conversations/${conversationId}/rating`, {
        method: "POST",
        body: JSON.stringify({
          rating: value,
          zone,
          formulation_snapshot: formulation,
        }),
      });
    } catch {
      toast.error(t("feedback.ratingFailed"));
      setRating(null);
      setShowComment(false);
    } finally {
      setSubmitting(false);
    }
  }, [conversationId, formulation, t]);

  const handleSubmitComment = useCallback(async () => {
    if (!rating || !comment.trim()) return;
    setSubmitting(true);

    try {
      const zone = getZoneFromPath(window.location.pathname);
      await api.request(`/api/v2/feedback/conversations/${conversationId}/rating`, {
        method: "POST",
        body: JSON.stringify({
          rating,
          comment: comment.trim(),
          zone,
          formulation_snapshot: formulation,
        }),
      });
      setSubmitted(true);
    } catch {
      toast.error(t("feedback.commentFailed"));
    } finally {
      setSubmitting(false);
    }
  }, [conversationId, formulation, rating, comment, t]);

  // After comment submitted, show thanks
  if (submitted) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <Check className="h-4 w-4 text-green-500" />
        <span>{t("feedback.thankYou")}</span>
      </div>
    );
  }

  return (
    <div className="space-y-2 py-2">
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">{t("feedback.rateFormulation")}</span>
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "h-8 w-8 p-0",
            rating === "up" && "text-green-500 bg-green-50 dark:bg-green-950"
          )}
          onClick={() => handleRate("up")}
          disabled={submitting}
        >
          <ThumbsUp className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "h-8 w-8 p-0",
            rating === "down" && "text-red-500 bg-red-50 dark:bg-red-950"
          )}
          onClick={() => handleRate("down")}
          disabled={submitting}
        >
          <ThumbsDown className="h-4 w-4" />
        </Button>
      </div>

      {/* Optional comment (appears after rating) */}
      {showComment && rating && (
        <div className="flex gap-2 items-end">
          <Textarea
            placeholder={t("feedback.commentPlaceholder")}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="min-h-[60px] text-sm resize-none"
            rows={2}
          />
          {comment.trim() && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleSubmitComment}
              disabled={submitting}
              className="flex-shrink-0"
            >
              <Send className="h-3 w-3" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

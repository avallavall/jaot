"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api, ModelCatalogItem } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { useAuth } from "@/contexts/AuthContext";
import { useTemplateTranslation } from "@/hooks/useTemplateTranslation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useDialog } from "@/components/ui/dialog-custom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  ArrowLeft,
  Star,
  CheckCircle,
  Building2,
  ExternalLink,
  Flag,
  Package,
  Shield,
} from "lucide-react";
import type { Review } from "@/lib/types";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { ModelTabs } from "@/components/marketplace/ModelTabs";
import { ImageGallery } from "@/components/marketplace/ImageGallery";

interface ReviewsResponse {
  items: Review[];
  total: number;
  avg_rating?: number;
  rating_distribution?: Record<number, number>;
}

export function ModelDetailClient({ modelId }: { modelId: string }) {
  const t = useTranslations("marketplace.detail");
  const router = useRouter();
  const dialog = useDialog();
  const { isAuthenticated } = useAuth();
  const tmpl = useTemplateTranslation(modelId);

  const [model, setModel] = useState<ModelCatalogItem | null>(null);
  const [reviews, setReviews] = useState<ReviewsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [isActivated, setIsActivated] = useState(false);
  const [activatedModelId, setActivatedModelId] = useState<string | null>(null);

  // Activation modal
  const [showActivateModal, setShowActivateModal] = useState(false);
  const [customName, setCustomName] = useState("");

  // Review form
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewTitle, setReviewTitle] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  // Report
  const [reportingReviewId, setReportingReviewId] = useState<string | null>(null);
  const [reportReason, setReportReason] = useState("");

  useEffect(() => {
    loadModel();
    loadReviews();
    checkIfActivated();
  }, [modelId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadModel = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getCatalogModel(modelId);
      setModel(data);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const loadReviews = async () => {
    try {
      const data = await api.getCatalogReviews(modelId);
      setReviews(data as unknown as ReviewsResponse);
    } catch (err) {
      console.warn('Failed to load reviews:', err);
    }
  };

  const checkIfActivated = async () => {
    if (!isAuthenticated) return;
    try {
      const myModels = await api.getMyModels();
      const activated = myModels.items.find(
        (s) => s.catalog_id === modelId
      );
      if (activated) {
        setIsActivated(true);
        setActivatedModelId(activated.id);
      }
    } catch (err) {
      console.warn('Failed to check activation status:', err);
    }
  };

  const handleActivateClick = () => {
    if (!model) return;

    if (!isAuthenticated) {
      router.push(`/login?returnUrl=/marketplace/${modelId}`);
      return;
    }

    setCustomName("");
    setShowActivateModal(true);
  };

  const confirmActivate = async () => {
    if (!model) return;

    setShowActivateModal(false);
    setActivating(true);
    try {
      const options = customName.trim() ? { customName: customName.trim() } : undefined;
      await api.activateCatalogModel(model.id, options);
      dialog.showSuccess(t("activatedSuccess"), t("activated"));
      setTimeout(() => router.push("/solve"), 1500);
    } catch (err) {
      const status = getErrorStatus(err);
      let msg: string;
      if (status === 402) {
        msg = t("insufficientCredits");
      } else if (status === 409) {
        msg = t("alreadyActivated");
      } else {
        msg = getErrorMessage(err, t("failedToActivate"));
      }
      dialog.showError(msg);
    } finally {
      setActivating(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!reviewRating) {
      return;
    }

    if (!isAuthenticated) {
      router.push(`/login?returnUrl=/marketplace/${modelId}`);
      return;
    }

    setSubmittingReview(true);
    try {
      await api.createReview(modelId, {
        rating: reviewRating,
        title: reviewTitle || undefined,
        comment: reviewComment || undefined,
      });
      dialog.showSuccess(t("reviewSubmitted"), t("thankYou"));
      setShowReviewForm(false);
      setReviewRating(5);
      setReviewTitle("");
      setReviewComment("");
      loadReviews();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedToSubmitReview")));
    } finally {
      setSubmittingReview(false);
    }
  };

  const handleReportReview = async (reviewId: string) => {
    if (!reportReason.trim()) {
      dialog.showError(t("provideReportReason"));
      return;
    }

    try {
      await api.reportReview(reviewId, { reason: reportReason });
      dialog.showSuccess(t("reportSubmitted"), t("reportThankYou"));
      setReportingReviewId(null);
      setReportReason("");
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("failedToReport")));
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12" aria-busy="true">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        <span className="sr-only">{t("loadingDetails")}</span>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg mb-4">
          {error || t("modelNotFound")}
        </div>
        <Button onClick={() => router.push("/marketplace")}>
          {t("backToCatalog")}
        </Button>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <Link
        href="/marketplace"
        className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        {t("backToCatalog")}
      </Link>

      <div className="bg-card border rounded-lg p-4 sm:p-8 mb-8">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
          <div className="flex items-start gap-4">
            {model.logo_url ? (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={model.logo_url} alt="" className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl object-cover flex-shrink-0" />
            ) : (
              <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-xl bg-muted flex items-center justify-center flex-shrink-0">
                <Package className="w-6 h-6 sm:w-8 sm:h-8 text-muted-foreground" />
              </div>
            )}
            <div>
              <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-2">
                <h1 className="text-xl sm:text-2xl font-bold">{tmpl.displayName(model.display_name)}</h1>
                {model.is_official && (
                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                    OFFICIAL
                  </span>
                )}
              </div>

              {model.author_name && (
                <div className="flex items-center gap-2 mb-4">
                  <Link
                    href={`/marketplace/sellers/${model.author_organization_id}`}
                    className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                  >
                    <Building2 className="w-4 h-4" />
                    {t("by", { author: model.author_name })}
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                  {model.author_verified && (
                    <Badge variant="default" className="gap-1 text-xs">
                      <Shield className="w-3 h-3" />
                      {t("verified")}
                    </Badge>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="text-left sm:text-right">
            <div className="text-2xl font-bold mb-2">
              {model.price_eur === 0 ? (
                <span className="text-green-600">{t("free")}</span>
              ) : (
                `${model.price_eur.toFixed(2)} \u20AC`
              )}
            </div>
            <div className="text-sm text-muted-foreground mb-4">
              {model.credits_per_execution > 0 ? (
                t("creditsPerRun", { credits: model.credits_per_execution })
              ) : (
                <span className="inline-flex items-center gap-1">
                  {t("dynamicCredits")}
                  <HelpTooltip content={t("dynamicCreditsTooltip")} side="left" size={14} />
                </span>
              )}
            </div>
            {isActivated ? (
              <Button
                onClick={() => router.push(`/solve/${activatedModelId}`)}
                size="lg"
                variant="outline"
                className="w-full sm:w-auto"
              >
                <CheckCircle className="w-4 h-4 mr-2" />
                {t("openModel")}
              </Button>
            ) : !isAuthenticated ? (
              <Button
                onClick={() => router.push(`/login?returnUrl=/marketplace/${modelId}`)}
                size="lg"
                className="w-full sm:w-auto"
              >
                {t("signInToActivate")}
              </Button>
            ) : (
              <Button onClick={handleActivateClick} disabled={activating} size="lg" className="w-full sm:w-auto">
                {activating ? t("activating") : t("activateModel")}
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-6 border-t">
          <div className="text-center">
            <div className="flex items-center justify-center gap-1 text-xl font-bold text-primary">
              <Star className="w-5 h-5 fill-current" />
              {model.avg_rating?.toFixed(1) || "\u2014"}
            </div>
            <div className="text-xs text-muted-foreground">{t("rating")}</div>
          </div>
          <div className="text-center">
            <div className="text-xl font-bold text-primary">
              {model.total_activations}
            </div>
            <div className="text-xs text-muted-foreground">{t("activations")}</div>
          </div>
          <div className="text-center">
            <div className="text-xl font-bold text-primary">
              {model.total_executions}
            </div>
            <div className="text-xs text-muted-foreground">{t("executions")}</div>
          </div>
          <div className="text-center">
            <div className="text-xl font-bold text-primary">
              {model.success_rate ? `${(model.success_rate * 100).toFixed(0)}%` : "\u2014"}
            </div>
            <div className="text-xs text-muted-foreground">{t("successRate")}</div>
          </div>
        </div>
      </div>

      {model.screenshot_urls && model.screenshot_urls.length > 0 && (
        <div className="bg-card border rounded-lg p-6 mb-8">
          <h2 className="text-lg font-semibold mb-4">{t("screenshots")}</h2>
          <ImageGallery screenshots={model.screenshot_urls} modelName={model.display_name} />
        </div>
      )}

      <div className="bg-card border rounded-lg p-6 mb-8">
        <ModelTabs model={model} />
      </div>

      {/* Fallback description for models without section content */}
      {model.description &&
        !model.section_overview &&
        !model.section_features &&
        !model.section_how_it_works &&
        !model.section_example_io &&
        !model.section_changelog && (
        <div className="bg-card border rounded-lg p-6 mb-8">
          <h2 className="text-lg font-semibold mb-4">{t("description")}</h2>
          <p className="text-muted-foreground whitespace-pre-wrap">
            {tmpl.description(model.description)}
          </p>
        </div>
      )}

      {model.tags && model.tags.length > 0 && (
        <div className="bg-card border rounded-lg p-6 mb-8">
          <div className="flex flex-wrap gap-2">
            {[...new Set(model.tags)].map((tag) => (
              <span
                key={tag}
                className="px-3 py-1 bg-muted rounded-full text-sm text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="bg-card border rounded-lg p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">
            {t("reviews")} {reviews && t("reviewCount", { count: reviews.total })}
          </h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowReviewForm(!showReviewForm)}
          >
            {t("writeReview")}
          </Button>
        </div>

        {reviews && reviews.total > 0 && (
          <div className="mb-6 p-4 bg-muted/50 rounded-lg">
            <div className="flex items-center gap-4">
              <div className="text-center">
                <div className="text-3xl font-bold text-primary">
                  {reviews.avg_rating?.toFixed(1)}
                </div>
                <div className="flex items-center justify-center gap-0.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <Star
                      key={star}
                      className={`w-4 h-4 ${
                        star <= (reviews.avg_rating || 0)
                          ? "fill-current text-primary"
                          : "text-muted-foreground"
                      }`}
                    />
                  ))}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {t("totalReviews", { count: reviews.total })}
                </div>
              </div>
              <div className="flex-1 space-y-1">
                {[5, 4, 3, 2, 1].map((rating) => (
                  <div key={rating} className="flex items-center gap-2 text-sm">
                    <span className="w-3">{rating}</span>
                    <Star className="w-3 h-3 text-muted-foreground" />
                    <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary"
                        style={{
                          width: `${
                            reviews.total > 0
                              ? (((reviews.rating_distribution?.[rating] ?? 0) / reviews.total) * 100)
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                    <span className="w-8 text-muted-foreground">
                      {reviews.rating_distribution?.[rating] ?? 0}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {showReviewForm && (
          <div className="mb-6 p-4 border rounded-lg">
            <h3 className="font-medium mb-4">{t("writeYourReview")}</h3>

            <div className="mb-4">
              <label className="block text-sm font-medium mb-2" id="review-rating-label">{t("reviewRating")}</label>
              <div className="flex gap-1" role="group" aria-labelledby="review-rating-label">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    onClick={() => setReviewRating(star)}
                    className="p-1 hover:scale-110 transition-transform"
                    aria-label={`Rate ${star} star${star !== 1 ? "s" : ""}`}
                  >
                    <Star
                      className={`w-6 h-6 ${
                        star <= reviewRating
                          ? "fill-current text-primary"
                          : "text-muted-foreground"
                      }`}
                    />
                  </button>
                ))}
              </div>
            </div>

            <div className="mb-4">
              <label htmlFor="review-title" className="block text-sm font-medium mb-2">{t("reviewTitleLabel")}</label>
              <input
                id="review-title"
                type="text"
                value={reviewTitle}
                onChange={(e) => setReviewTitle(e.target.value)}
                placeholder={t("reviewTitlePlaceholder")}
                className="w-full px-3 py-2 border rounded-md bg-background"
                maxLength={200}
              />
            </div>

            <div className="mb-4">
              <label htmlFor="review-comment" className="block text-sm font-medium mb-2">{t("reviewCommentLabel")}</label>
              <Textarea
                id="review-comment"
                value={reviewComment}
                onChange={(e) => setReviewComment(e.target.value)}
                placeholder={t("reviewCommentPlaceholder")}
                className="min-h-[100px]"
                maxLength={2000}
              />
            </div>

            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setShowReviewForm(false)}
              >
                {t("cancel")}
              </Button>
              <Button
                onClick={handleSubmitReview}
                disabled={submittingReview}
              >
                {submittingReview ? t("submitting") : t("submitReview")}
              </Button>
            </div>
          </div>
        )}

        {reviews && reviews.items.length > 0 ? (
          <div className="space-y-4">
            {reviews.items.map((review) => (
              <div key={review.id} className="border-b pb-4 last:border-0">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/user/${review.user_id}`}
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {review.user_name}
                      </Link>
                      {review.organization_name && (
                        <span className="text-xs text-muted-foreground">
                          {t("from", { organization: review.organization_name })}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 mt-1">
                      {[1, 2, 3, 4, 5].map((star) => (
                        <Star
                          key={star}
                          className={`w-4 h-4 ${
                            star <= review.rating
                              ? "fill-current text-primary"
                              : "text-muted-foreground"
                          }`}
                        />
                      ))}
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(review.created_at).toLocaleDateString()}
                  </span>
                </div>

                {review.title && (
                  <h4 className="font-medium mb-1">{review.title}</h4>
                )}

                {review.comment && (
                  <p className="text-sm text-muted-foreground">{review.comment}</p>
                )}

                <div className="mt-2 flex justify-end">
                  {reportingReviewId === review.id ? (
                    <div className="flex items-center gap-2 w-full">
                      <input
                        type="text"
                        value={reportReason}
                        onChange={(e) => setReportReason(e.target.value)}
                        placeholder={t("reportPlaceholder")}
                        className="flex-1 px-2 py-1 text-sm border rounded bg-background"
                        maxLength={500}
                      />
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleReportReview(review.id)}
                      >
                        {t("submitReview")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setReportingReviewId(null);
                          setReportReason("");
                        }}
                      >
                        {t("cancel")}
                      </Button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setReportingReviewId(review.id)}
                      className="text-xs text-muted-foreground hover:text-destructive flex items-center gap-1"
                      title={t("reportReview")}
                    >
                      <Flag className="w-3 h-3" />
                      {t("report")}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            {t("noReviews")}
          </div>
        )}
      </div>

      <Dialog open={showActivateModal} onOpenChange={(open) => { if (!open) setShowActivateModal(false); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("activateModal.title")}</DialogTitle>
            <DialogDescription>
              {t("activateModal.description")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li>{t("activateModal.bringToWorkspace")}</li>
              <li>{t("activateModal.ownCopy")}</li>
              {model && model.price_eur > 0 && (
                <li className="font-medium text-foreground">
                  {t("activateModal.cost", { price: model.price_eur.toFixed(2) })}
                </li>
              )}
            </ul>
            <div>
              <label htmlFor="activate-custom-name" className="text-sm font-medium block mb-1.5">
                {t("activateModal.customNameLabel")}
              </label>
              <Input
                id="activate-custom-name"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                placeholder={model?.display_name ?? ""}
                maxLength={255}
                onKeyDown={(e) => { if (e.key === "Enter") confirmActivate(); }}
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t("activateModal.customNameHint")}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowActivateModal(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={confirmActivate}>
              {t("activateModal.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <dialog.DialogComponent />
    </div>
  );
}

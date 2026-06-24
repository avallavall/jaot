"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useDialog } from "@/components/ui/dialog-custom";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Flag, Star, Trash2, Eye, EyeOff, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";

interface ReportedReview {
  id: string;
  model_id: string;
  model_name?: string;
  user_id: string;
  user_name?: string;
  rating: number;
  comment?: string;
  report_count: number;
  report_reasons: string[];
  is_visible: boolean;
  created_at: string;
}

export default function ReportedReviewsPage() {
  const t = useTranslations("admin.reviews");
  const tc = useTranslations("common");
  const dialog = useDialog();
  const [reviews, setReviews] = useState<ReportedReview[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadReviews();
  }, []);

  const loadReviews = async () => {
    setLoading(true);
    try {
      const data = await api.request("/api/v2/admin/reviews/reported") as { items: ReportedReview[] };
      setReviews(data.items || []);
    } catch (err) {
      console.warn('Failed to load reported reviews:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleVisibility = async (reviewId: string, currentlyVisible: boolean) => {
    try {
      await api.request(`/api/v2/admin/reviews/${reviewId}/visibility?visible=${!currentlyVisible}`, {
        method: "PATCH",
      });
      dialog.showSuccess(
        currentlyVisible ? t("reviewHidden") : t("reviewVisible"),
        currentlyVisible ? t("hiddenMessage") : t("visibleMessage")
      );
      loadReviews();
    } catch {
      dialog.showError(t("visibilityError"));
    }
  };

  const handleDelete = async (reviewId: string) => {
    const confirmed = await dialog.confirm(
      t("deleteConfirm"),
      t("deleteTitle")
    );
    if (!confirmed) return;

    try {
      await api.request(`/api/v2/admin/reviews/${reviewId}`, {
        method: "DELETE",
      });
      dialog.showSuccess(t("deleted"), t("deletedMessage"));
      loadReviews();
    } catch {
      dialog.showError(t("deleteError"));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">
          {t("subtitle")}
        </p>
      </div>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-lg font-serif flex items-center gap-2">
            <Flag className="w-5 h-5 text-destructive" />
            {t("flaggedReviews", { count: reviews.length })}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.model")}</TableHead>
                <TableHead>{t("tableHeaders.user")}</TableHead>
                <TableHead>{t("tableHeaders.rating")}</TableHead>
                <TableHead>{t("tableHeaders.comment")}</TableHead>
                <TableHead>{t("tableHeaders.reports")}</TableHead>
                <TableHead>{t("tableHeaders.status")}</TableHead>
                <TableHead>{t("tableHeaders.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : reviews.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {t("noReported")}
                  </TableCell>
                </TableRow>
              ) : (
                reviews.map((review) => (
                  <TableRow key={review.id} className="border-border">
                    <TableCell>
                      <Link
                        href={`/marketplace/${review.model_id}`}
                        className="flex items-center gap-1 hover:text-primary"
                      >
                        {review.model_name}
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/user/${review.user_id}`}
                        className="hover:text-primary"
                      >
                        {review.user_name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Star className="w-4 h-4 fill-current text-primary" />
                        {review.rating}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-xs truncate" title={review.comment}>
                      {review.comment || <span className="text-muted-foreground italic">{t("noComment")}</span>}
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <Badge variant="destructive">{t("reportCount", { count: review.report_count })}</Badge>
                        {review.report_reasons.length > 0 && (
                          <div className="text-xs text-muted-foreground">
                            {review.report_reasons.slice(0, 2).join(", ")}
                            {review.report_reasons.length > 2 && "..."}
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={review.is_visible ? "default" : "secondary"}>
                        {review.is_visible ? t("visible") : t("hidden")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleToggleVisibility(review.id, review.is_visible)}
                          title={review.is_visible ? t("hideReview") : t("showReview")}
                        >
                          {review.is_visible ? (
                            <EyeOff className="w-4 h-4" />
                          ) : (
                            <Eye className="w-4 h-4" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDelete(review.id)}
                          title={t("deleteReview")}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <dialog.DialogComponent />
    </div>
  );
}

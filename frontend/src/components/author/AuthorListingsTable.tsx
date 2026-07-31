"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ExternalLink, Loader2, PackageOpen, Pencil, Star } from "lucide-react";

import { api } from "@/lib/api";
import type { AuthorListingRow } from "@/lib/types";
import { Link } from "@/i18n/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface AuthorListingsTableProps {
  listings: AuthorListingRow[];
  onChanged: (updated: AuthorListingRow) => void;
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  published: "default",
  unpublished: "secondary",
  draft: "outline",
};

export function AuthorListingsTable({ listings, onChanged }: AuthorListingsTableProps) {
  const t = useTranslations("author.listings");
  const [busyId, setBusyId] = useState<string | null>(null);

  if (listings.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <PackageOpen className="h-8 w-8 text-muted-foreground" />
          <p className="font-medium">{t("emptyTitle")}</p>
          <p className="max-w-md text-sm text-muted-foreground">{t("emptyBody")}</p>
          <Button asChild variant="outline" className="mt-2">
            <Link href="/studio">{t("emptyCta")}</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const toggle = async (row: AuthorListingRow) => {
    const withdrawing = row.status === "published";
    setBusyId(row.model_project_id);
    try {
      if (withdrawing) {
        await api.unpublishModelProject(row.model_project_id);
      } else {
        await api.republishModelProject(row.model_project_id);
      }
      onChanged({ ...row, status: withdrawing ? "unpublished" : "published" });
      toast.success(withdrawing ? t("withdrawnToast") : t("restoredToast"));
    } catch {
      toast.error(t("actionFailed"));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("colModel")}</TableHead>
            <TableHead>{t("colStatus")}</TableHead>
            <TableHead className="text-right">{t("colAdoptions")}</TableHead>
            <TableHead className="text-right">{t("colRuns")}</TableHead>
            <TableHead className="text-right">{t("colRating")}</TableHead>
            <TableHead className="text-right">{t("colActions")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {listings.map((row) => {
            const isPublished = row.status === "published";
            // Only this pair round-trips; the server refuses to promote anything
            // else, so offering the button would be offering a 409.
            const canToggle = isPublished || row.status === "unpublished";
            const busy = busyId === row.model_project_id;
            return (
              <TableRow key={row.model_project_id}>
                <TableCell>
                  <div className="font-medium">{row.display_name}</div>
                  {row.short_description && (
                    <div className="line-clamp-1 text-xs text-muted-foreground">
                      {row.short_description}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[row.status] ?? "outline"}>
                    {/* The column holds states this table does not name (the seeder
                        retires templates as "deprecated"); show the raw state rather
                        than a translation key nobody wrote. */}
                    {t.has(`status.${row.status}`) ? t(`status.${row.status}`) : row.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.total_activations.toLocaleString()}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.total_executions.toLocaleString()}
                </TableCell>
                <TableCell className="text-right">
                  {row.avg_rating === null ? (
                    <span className="text-muted-foreground">{t("noRating")}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 tabular-nums">
                      <Star className="h-3 w-3 fill-current text-amber-500" />
                      {row.avg_rating.toFixed(1)}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-2">
                    {/* Edit is where the logo and screenshots live — without it the
                        "add rich media" checklist step has nowhere to send anyone. */}
                    <Button asChild variant="ghost" size="sm" className="gap-1">
                      <Link href={`/studio/${row.model_project_id}/publish`}>
                        <Pencil className="h-3 w-3" />
                        {t("edit")}
                      </Link>
                    </Button>
                    {/* The catalog needs BOTH: an unlisted model 404s just like a
                        withdrawn one, so linking on status alone offers a dead page. */}
                    {isPublished && row.is_public && (
                      <Button asChild variant="ghost" size="sm" className="gap-1">
                        <Link href={`/marketplace/${row.model_project_id}`}>
                          <ExternalLink className="h-3 w-3" />
                          {t("viewPublic")}
                        </Link>
                      </Button>
                    )}
                    {canToggle && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() => toggle(row)}
                      >
                        {busy && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                        {isPublished ? t("withdraw") : t("restore")}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

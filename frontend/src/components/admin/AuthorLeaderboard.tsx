"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslations } from "next-intl";

export interface AuthorLeaderboardEntry {
  org_id: string;
  org_name: string;
  total_activations: number;
  models_published: number;
  avg_rating: number | null;
}

interface AuthorLeaderboardProps {
  authors: AuthorLeaderboardEntry[];
}

export function AuthorLeaderboard({ authors }: AuthorLeaderboardProps) {
  const t = useTranslations("admin.marketplace");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("authorLeaderboard")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {authors.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("noAuthorData")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">{t("rank")}</TableHead>
                <TableHead>{t("authorName")}</TableHead>
                <TableHead className="text-right">{t("totalActivations")}</TableHead>
                <TableHead className="text-right">
                  {t("modelsPublished")}
                </TableHead>
                <TableHead className="text-right">{t("avgRating")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {authors.map((author, idx) => (
                <TableRow key={author.org_id}>
                  <TableCell className="font-medium">{idx + 1}</TableCell>
                  {/* No per-author drill-down route exists (audit F-07): the old
                      per-org analytics link hard-404'd, and this table already
                      lives on the only analytics page. */}
                  <TableCell className="font-medium">{author.org_name}</TableCell>
                  <TableCell className="text-right">
                    {author.total_activations.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {author.models_published}
                  </TableCell>
                  <TableCell className="text-right">
                    {author.avg_rating !== null
                      ? author.avg_rating.toFixed(1)
                      : "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

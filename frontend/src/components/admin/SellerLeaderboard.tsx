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
import type { SellerLeaderboardEntry } from "@/lib/types";

interface SellerLeaderboardProps {
  sellers: SellerLeaderboardEntry[];
}

export function SellerLeaderboard({ sellers }: SellerLeaderboardProps) {
  const t = useTranslations("admin.marketplace");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("sellerLeaderboard")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {sellers.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("noSellerData")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">{t("rank")}</TableHead>
                <TableHead>{t("sellerName")}</TableHead>
                <TableHead className="text-right">{t("totalSales")}</TableHead>
                <TableHead className="text-right">
                  {t("totalRevenue")}
                </TableHead>
                <TableHead className="text-right">
                  {t("modelsPublished")}
                </TableHead>
                <TableHead className="text-right">{t("avgRating")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sellers.map((seller, idx) => (
                <TableRow key={seller.org_id}>
                  <TableCell className="font-medium">{idx + 1}</TableCell>
                  {/* No per-seller drill-down route exists (audit F-07): the old
                      /admin/marketplace/seller-analytics/[orgId] link hard-404'd,
                      and this table already lives on the only analytics page. */}
                  <TableCell className="font-medium">{seller.org_name}</TableCell>
                  <TableCell className="text-right">
                    {seller.total_sales.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {seller.total_revenue.toLocaleString()} {t("creditsUnit")}
                  </TableCell>
                  <TableCell className="text-right">
                    {seller.models_published}
                  </TableCell>
                  <TableCell className="text-right">
                    {seller.avg_rating !== null
                      ? seller.avg_rating.toFixed(1)
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

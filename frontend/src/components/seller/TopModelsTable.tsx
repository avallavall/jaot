"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTranslations } from "next-intl";
import type { ModelPerformanceRow } from "@/lib/types";

interface TopModelsTableProps {
  data: ModelPerformanceRow[];
}

export function TopModelsTable({ data }: TopModelsTableProps) {
  const t = useTranslations("seller.analytics");

  // Sort by revenue descending
  const sorted = [...data].sort((a, b) => b.revenue - a.revenue);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("modelPerformance")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("noData")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("modelName")}</TableHead>
                <TableHead className="text-right">{t("views")}</TableHead>
                <TableHead className="text-right">
                  {t("activations")}
                </TableHead>
                <TableHead className="text-right">{t("revenue")}</TableHead>
                <TableHead className="text-right">
                  {t("conversionRate")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => (
                <TableRow key={row.model_id}>
                  <TableCell className="font-medium">
                    {row.model_name}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.views.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.activations.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.revenue.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {row.conversion_rate}%
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

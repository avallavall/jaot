"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import type { SaleRecord } from "@/lib/api";

interface SalesHistoryTableProps {
  sales: SaleRecord[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function SalesHistoryTable({
  sales,
  total,
  page,
  pageSize,
  onPageChange,
}: SalesHistoryTableProps) {
  const t = useTranslations("seller.earnings");
  const totalPages = Math.ceil(total / pageSize);

  if (sales.length === 0) {
    return (
      <div className="bg-card border rounded-lg p-8 text-center">
        <p className="text-muted-foreground">{t("noSales")}</p>
      </div>
    );
  }

  return (
    <div className="bg-card border rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/30">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                {t("date")}
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                {t("model")}
              </th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                {t("buyer")}
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                {t("salePrice")}
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                {t("commission")}
              </th>
              <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                {t("yourEarning")}
              </th>
            </tr>
          </thead>
          <tbody>
            {sales.map((sale) => (
              <tr key={sale.sale_id} className="border-b last:border-0 hover:bg-muted/20">
                <td className="px-4 py-3 text-muted-foreground">
                  {new Date(sale.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 font-medium">
                  {sale.model_name || sale.model_id || "-"}
                </td>
                <td className="px-4 py-3">
                  {sale.buyer_organization_name || "-"}
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  {sale.credits_price.toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400">
                    -{sale.commission_amount.toLocaleString()}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400">
                    +{sale.seller_earning.toLocaleString()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t">
          <div className="text-sm text-muted-foreground">
            {t("credits", { amount: `${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, total)} / ${total}` })}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import type { PaginatedResponse } from "@/lib/types";

interface AdminOrganizationCredit {
  id: string;
  name: string;
  credits_balance: number;
}

interface AdminTransaction {
  id: string;
  organization_id: string;
  transaction_type: string;
  amount: number;
  balance_after: number;
  description?: string;
  created_at: string;
}

export default function CreditsPage() {
  const t = useTranslations("admin.credits");
  const tc = useTranslations("common");
  const { transactionTypeLabel } = useCommonLabels();
  const [organizations, setOrganizations] = useState<AdminOrganizationCredit[]>([]);
  const [transactions, setTransactions] = useState<AdminTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [orgFilter, setOrgFilter] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [isAdjustOpen, setIsAdjustOpen] = useState(false);
  const [selectedOrg, setSelectedOrg] = useState<AdminOrganizationCredit | null>(null);
  const [adjustAmount, setAdjustAmount] = useState("");
  const [adjustReason, setAdjustReason] = useState("");

  useEffect(() => {
    loadOrganizations();
    loadTransactions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadTransactions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, orgFilter]);

  const loadOrganizations = async () => {
    try {
      const data = await api.admin.getOrganizations({}) as { items: AdminOrganizationCredit[] };
      setOrganizations(data.items);
    } catch (err) {
      console.warn('Failed to load organizations:', err);
    }
  };

  const loadTransactions = async () => {
    setLoading(true);
    try {
      const data = await api.request<PaginatedResponse<AdminTransaction>>(
        `/api/v2/admin/credits/transactions?page=${page}${orgFilter ? `&organization_id=${orgFilter}` : ''}`
      );
      setTransactions(data.items);
      setTotalPages(data.total_pages ?? 1);
    } catch (err) {
      console.warn('Failed to load transactions:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAdjust = async () => {
    if (!selectedOrg || !adjustAmount || !adjustReason) return;

    try {
      await api.admin.adjustCredits({
        organization_id: selectedOrg.id,
        amount: parseInt(adjustAmount),
        reason: adjustReason,
      });
      setIsAdjustOpen(false);
      setSelectedOrg(null);
      setAdjustAmount("");
      setAdjustReason("");
      loadOrganizations();
      loadTransactions();
    } catch {
      toast.error(t("adjustFailed"));
    }
  };

  const getOrgName = (orgId: string) => {
    const org = organizations.find(o => o.id === orgId);
    return org?.name || orgId;
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
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
          <CardTitle className="text-lg font-serif">{t("orgBalances")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {organizations.map(org => (
              <div
                key={org.id}
                className="p-4 border border-border bg-card hover:bg-muted/50 transition-colors cursor-pointer"
                onClick={() => {
                  setSelectedOrg(org);
                  setIsAdjustOpen(true);
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{org.name}</span>
                  <Badge variant="outline">{t("clickToAdjust")}</Badge>
                </div>
                <div className="mt-2">
                  <span className="text-2xl font-bold text-primary">
                    {org.credits_balance.toLocaleString()}
                  </span>
                  <span className="text-muted-foreground ml-1">{t("credits")}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Dialog open={isAdjustOpen} onOpenChange={setIsAdjustOpen}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="font-serif">
              {t("adjustCredits")} - {selectedOrg?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="p-4 bg-muted border border-border">
              <p className="text-sm text-muted-foreground">{t("currentBalance")}</p>
              <p className="text-2xl font-bold">
                {selectedOrg?.credits_balance.toLocaleString()} {t("credits")}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="amount">{t("amountLabel")}</Label>
              <Input
                id="amount"
                type="number"
                value={adjustAmount}
                onChange={(e) => setAdjustAmount(e.target.value)}
                placeholder={t("amountPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reason">{t("reason")}</Label>
              <Input
                id="reason"
                value={adjustReason}
                onChange={(e) => setAdjustReason(e.target.value)}
                placeholder={t("reasonPlaceholder")}
              />
            </div>
            {adjustAmount && (
              <div className="p-3 bg-muted border border-border">
                <p className="text-sm">
                  {t.rich("newBalance", {
                    amount: ((selectedOrg?.credits_balance || 0) + parseInt(adjustAmount || "0")).toLocaleString(),
                    b: (chunks) => <strong>{chunks}</strong>,
                  })}
                </p>
              </div>
            )}
            <Button
              onClick={handleAdjust}
              disabled={!adjustAmount || !adjustReason}
              className="w-full bg-primary text-primary-foreground"
            >
              {t("applyAdjustment")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Card className="border-border">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg font-serif">{t("transactionHistory")}</CardTitle>
          <select
            value={orgFilter}
            onChange={(e) => setOrgFilter(e.target.value)}
            className="p-2 border border-input bg-background text-sm"
          >
            <option value="">{t("allOrganizations")}</option>
            {organizations.map(org => (
              <option key={org.id} value={org.id}>{org.name}</option>
            ))}
          </select>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.date")}</TableHead>
                <TableHead>{t("tableHeaders.organization")}</TableHead>
                <TableHead>{t("tableHeaders.type")}</TableHead>
                <TableHead>{t("tableHeaders.amount")}</TableHead>
                <TableHead>{t("tableHeaders.balanceAfter")}</TableHead>
                <TableHead>{t("tableHeaders.description")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : transactions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    {t("noTransactions")}
                  </TableCell>
                </TableRow>
              ) : (
                transactions.map((txn) => (
                  <TableRow key={txn.id} className="border-border">
                    <TableCell className="text-muted-foreground text-sm">
                      {formatDate(txn.created_at)}
                    </TableCell>
                    <TableCell>{getOrgName(txn.organization_id)}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{transactionTypeLabel(txn.transaction_type)}</Badge>
                    </TableCell>
                    <TableCell>
                      <span className={(txn.amount ?? 0) >= 0 ? "text-green-600" : "text-red-600"}>
                        {(txn.amount ?? 0) >= 0 ? "+" : ""}{(txn.amount ?? 0).toLocaleString()}
                      </span>
                    </TableCell>
                    <TableCell>{(txn.balance_after ?? 0).toLocaleString()}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {txn.description || "-"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            {tc("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageOf", { page, totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            {tc("next")}
          </Button>
        </div>
      )}
    </div>
  );
}

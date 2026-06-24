"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { SettingsAuditEntry } from "@/lib/api";
import { useTranslations } from "next-intl";

interface AuditLogTabProps {
  categories: string[];
}

export function AuditLogTab({ categories }: AuditLogTabProps) {
  const t = useTranslations("admin.settings");
  const [items, setItems] = useState<SettingsAuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(true);

  // Filters
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [filterAdmin, setFilterAdmin] = useState<string>("");

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const fetchAudit = useCallback(async () => {
    setLoading(true);
    try {
      const params: { page: number; page_size: number; category?: string; changed_by?: string } = {
        page,
        page_size: pageSize,
      };
      if (filterCategory) params.category = filterCategory;
      if (filterAdmin.trim()) params.changed_by = filterAdmin.trim();
      const result = await api.admin.getSettingsAudit(params);
      setItems(result.items);
      setTotal(result.total);
    } catch {
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filterCategory, filterAdmin]);

  useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  const handleCategoryChange = (value: string) => {
    setFilterCategory(value === "__all__" ? "" : value);
    setPage(1);
  };

  const formatDate = (dateStr: string) => {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(dateStr));
  };

  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-serif">{t("audit.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-4">
          <div className="w-48">
            <Select value={filterCategory || "__all__"} onValueChange={handleCategoryChange}>
              <SelectTrigger>
                <SelectValue placeholder={t("audit.filterCategory")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">{t("audit.allCategories")}</SelectItem>
                {categories.map((cat) => (
                  <SelectItem key={cat} value={cat}>
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-48">
            <Input
              placeholder={t("audit.filterAdmin")}
              value={filterAdmin}
              onChange={(e) => {
                setFilterAdmin(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>

        <div className="overflow-x-auto border border-border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("audit.columns.date")}</TableHead>
                <TableHead>{t("audit.columns.settingKey")}</TableHead>
                <TableHead>{t("audit.columns.oldValue")}</TableHead>
                <TableHead>{t("audit.columns.newValue")}</TableHead>
                <TableHead>{t("audit.columns.changedBy")}</TableHead>
                <TableHead>{t("audit.columns.category")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    ...
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    {t("audit.noEntries")}
                  </TableCell>
                </TableRow>
              ) : (
                items.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap text-sm">
                      {formatDate(entry.changed_at)}
                    </TableCell>
                    <TableCell className="font-mono text-sm">{entry.setting_key}</TableCell>
                    <TableCell className="text-sm max-w-[200px] truncate">
                      {entry.old_value ?? <span className="text-muted-foreground">-</span>}
                    </TableCell>
                    <TableCell className="text-sm max-w-[200px] truncate">
                      {entry.new_value !== null ? (
                        entry.new_value
                      ) : (
                        <span className="italic text-muted-foreground">
                          {t("audit.resetToDefault")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{entry.changed_by}</TableCell>
                    <TableCell className="text-sm capitalize">{entry.category ?? "-"}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {total > pageSize && (
          <div className="flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
            >
              {t("audit.pagination.previous")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t("audit.pagination.page", { page, total: totalPages })}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
            >
              {t("audit.pagination.next")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

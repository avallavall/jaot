"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Activity, Clock, Coins, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import type { PaginatedResponse } from "@/lib/types";

interface AdminExecution {
  id: string;
  model_id: string;
  model_name?: string;
  organization_id: string;
  organization_name?: string;
  status: string;
  credits_consumed: number;
  execution_time_ms: number | null;
  created_at: string;
}

export default function AdminExecutionsPage() {
  const t = useTranslations("admin.executions");
  const tc = useTranslations("common");
  const [executions, setExecutions] = useState<AdminExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("all");

  useEffect(() => {
    loadExecutions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter]);

  const loadExecutions = async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        page,
        page_size: 20,
      };
      if (statusFilter !== "all") {
        params.status = statusFilter;
      }

      const queryString = new URLSearchParams(
        Object.entries(params).map(([k, v]) => [k, String(v)])
      ).toString();

      const data = await api.request(`/api/v2/models/executions/all?${queryString}`) as PaginatedResponse<AdminExecution>;
      setExecutions(data.items || []);
      setTotalPages(data.total_pages ?? 1);
    } catch (err) {
      console.warn('Failed to load executions:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const formatDuration = (ms: number | null) => {
    if (ms === null) return "-";
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <Badge className="bg-green-600">{t("completed")}</Badge>;
      case "failed":
        return <Badge variant="destructive">{t("failed")}</Badge>;
      case "running":
        return <Badge className="bg-blue-600">{t("running")}</Badge>;
      case "pending":
        return <Badge variant="secondary">{t("pending")}</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  // Calculate stats
  const totalCredits = executions.reduce((sum, e) => sum + (e.credits_consumed || 0), 0);
  const avgTime = executions.length > 0
    ? executions.reduce((sum, e) => sum + (e.execution_time_ms || 0), 0) / executions.length
    : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">
          {t("subtitle")}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-border">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Activity className="w-8 h-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">{t("totalShown")}</p>
                <p className="text-2xl font-bold">{executions.length}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Coins className="w-8 h-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">{t("creditsUsed")}</p>
                <p className="text-2xl font-bold">{totalCredits}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Clock className="w-8 h-8 text-primary" />
              <div>
                <p className="text-sm text-muted-foreground">{t("avgTime")}</p>
                <p className="text-2xl font-bold">{formatDuration(avgTime)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-4">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder={tc("status")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allStatus")}</SelectItem>
            <SelectItem value="completed">{t("completed")}</SelectItem>
            <SelectItem value="failed">{t("failed")}</SelectItem>
            <SelectItem value="running">{t("running")}</SelectItem>
            <SelectItem value="pending">{t("pending")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card className="border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.id")}</TableHead>
                <TableHead>{t("tableHeaders.model")}</TableHead>
                <TableHead>{t("tableHeaders.organization")}</TableHead>
                <TableHead>{t("tableHeaders.status")}</TableHead>
                <TableHead>{t("tableHeaders.credits")}</TableHead>
                <TableHead>{t("tableHeaders.duration")}</TableHead>
                <TableHead>{t("tableHeaders.date")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : executions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {t("noExecutions")}
                  </TableCell>
                </TableRow>
              ) : (
                executions.map((exec) => (
                  <TableRow key={exec.id} className="border-border">
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {exec.id.slice(0, 8)}...
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/marketplace/${exec.model_id}`}
                        className="flex items-center gap-1 hover:text-primary"
                      >
                        {exec.model_name || exec.model_id}
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/org/${exec.organization_id}`}
                        className="hover:text-primary"
                      >
                        {exec.organization_name || exec.organization_id}
                      </Link>
                    </TableCell>
                    <TableCell>{getStatusBadge(exec.status)}</TableCell>
                    <TableCell>{exec.credits_consumed}</TableCell>
                    <TableCell>{formatDuration(exec.execution_time_ms)}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatDate(exec.created_at)}
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

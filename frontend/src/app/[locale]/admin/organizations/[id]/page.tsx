"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  Activity,
  ArrowLeft,
  Coins,
  Key,
  Package,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AdminOrganizationOverview } from "@/types/admin";

const RECENT_LIMIT = 20;

export default function OrganizationDetailPage() {
  const t = useTranslations("admin.orgDetail");
  const locale = useLocale();
  const params = useParams();
  const orgId = params.id as string;

  const [data, setData] = useState<AdminOrganizationOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const overview = await api.admin.getOrganizationOverview(orgId);
      setData(overview);
    } catch (err) {
      // A 404 means the org doesn't exist; anything else is a real load error
      // we must surface instead of silently showing an empty page.
      if (getErrorStatus(err) === 404) {
        setNotFound(true);
      } else {
        setError(getErrorMessage(err, t("loadError")));
      }
    } finally {
      setLoading(false);
    }
  }, [orgId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const fmtDateTime = (s: string | null | undefined) =>
    s ? new Date(s).toLocaleString(locale) : "—";
  const fmtDate = (s: string | null | undefined) =>
    s ? new Date(s).toLocaleDateString(locale) : "—";
  const num = (n: number) => n.toLocaleString(locale);

  const backLink = (
    <Link
      href="/admin/organizations"
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="w-4 h-4" /> {t("back")}
    </Link>
  );

  if (loading) {
    return (
      <div className="space-y-6">
        {backLink}
        <p className="text-muted-foreground">{t("loading")}</p>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="space-y-6">
        {backLink}
        <Card className="border-border">
          <CardContent className="py-10 text-center text-muted-foreground">
            {t("notFound")}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-6">
        {backLink}
        <Card className="border-border">
          <CardContent className="py-10 text-center space-y-4">
            <p className="text-destructive">{error ?? t("loadError")}</p>
            <Button variant="outline" onClick={load}>
              {t("retry")}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { organization: org, owner, counts, execution_stats: stats } = data;

  const planVariant =
    org.plan === "business"
      ? "default"
      : org.plan === "pro"
        ? "secondary"
        : "outline";

  const statusBadge = (status: string) => {
    const v =
      status === "completed"
        ? "default"
        : status === "failed" || status === "timeout" || status === "cancelled"
          ? "destructive"
          : "secondary";
    return <Badge variant={v}>{status}</Badge>;
  };

  const kpis = [
    { icon: <Users className="w-4 h-4" />, label: t("kpi.users"), value: num(counts.users) },
    { icon: <Key className="w-4 h-4" />, label: t("kpi.apiKeys"), value: num(counts.api_keys) },
    { icon: <Package className="w-4 h-4" />, label: t("kpi.models"), value: num(counts.models) },
    {
      icon: <Activity className="w-4 h-4" />,
      label: t("kpi.executions"),
      value: num(counts.executions),
    },
    {
      icon: <Coins className="w-4 h-4" />,
      label: t("kpi.creditsBalance"),
      value: num(org.credits_balance),
    },
    {
      icon: <Coins className="w-4 h-4" />,
      label: t("kpi.creditsUsedMonth"),
      value: num(org.credits_used_month),
    },
  ];

  const configRows: { label: string; value: React.ReactNode }[] = [
    { label: t("config.plan"), value: <Badge variant={planVariant}>{org.plan}</Badge> },
    { label: t("config.owner"), value: owner ? `${owner.name} (${owner.email ?? "—"})` : "—" },
    { label: t("config.monthlyQuota"), value: num(org.monthly_quota) },
    { label: t("config.rateLimitMin"), value: num(org.rate_limit_per_minute) },
    { label: t("config.rateLimitDay"), value: num(org.rate_limit_per_day) },
    { label: t("config.maxPrivatePlugins"), value: num(org.max_private_plugins) },
    { label: t("config.currency"), value: org.currency },
    {
      label: t("config.aiBuilder"),
      value: org.ai_builder_enabled ? t("enabled") : t("disabled"),
    },
    { label: t("config.byok"), value: org.byok_configured ? t("yes") : t("no") },
    {
      label: t("config.active"),
      value: <Badge variant={org.is_active ? "default" : "secondary"}>{org.is_active ? t("active") : t("inactive")}</Badge>,
    },
    { label: t("config.verified"), value: org.is_verified ? t("yes") : t("no") },
    { label: t("config.publicProfile"), value: org.is_public_profile ? t("yes") : t("no") },
    { label: t("config.slug"), value: org.slug ?? "—" },
    { label: t("config.billingEmail"), value: org.billing_email ?? "—" },
    {
      label: t("config.website"),
      value: org.website_url ? (
        <a href={org.website_url} target="_blank" rel="noopener noreferrer" className="text-primary underline">
          {org.website_url}
        </a>
      ) : (
        "—"
      ),
    },
    { label: t("config.createdAt"), value: fmtDate(org.created_at) },
  ];

  const creditRows = [
    { label: t("credits.balance"), value: num(org.credits_balance) },
    { label: t("credits.subscription"), value: num(org.credits_subscription) },
    { label: t("credits.purchased"), value: num(org.credits_purchased) },
    { label: t("credits.earned"), value: num(org.credits_earned) },
    { label: t("credits.usedMonth"), value: num(org.credits_used_month) },
  ];

  return (
    <div className="space-y-6">
      {backLink}

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-3xl font-serif text-foreground">{org.name}</h1>
            <Badge variant={planVariant}>{org.plan}</Badge>
            {org.is_verified && <Badge variant="secondary">✓ {t("config.verified")}</Badge>}
            <Badge variant={org.is_active ? "default" : "secondary"}>
              {org.is_active ? t("active") : t("inactive")}
            </Badge>
          </div>
          <p className="text-muted-foreground mt-1 font-mono text-xs">{org.id}</p>
        </div>
        <span className="text-xs text-muted-foreground border border-border rounded px-2 py-1">
          {t("readonlyNote")}
        </span>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label} className="border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground text-sm">
                {kpi.icon}
                {kpi.label}
              </div>
              <div className="text-2xl font-semibold mt-1 text-foreground">{kpi.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Configuration */}
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="font-serif text-xl">{t("sections.configuration")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="divide-y divide-border">
              {configRows.map((row) => (
                <div key={row.label} className="flex items-center justify-between py-2 gap-4">
                  <dt className="text-sm text-muted-foreground">{row.label}</dt>
                  <dd className="text-sm text-foreground text-right">{row.value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        {/* Credits + execution stats */}
        <div className="space-y-6">
          <Card className="border-border">
            <CardHeader>
              <CardTitle className="font-serif text-xl">{t("sections.credits")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="divide-y divide-border">
                {creditRows.map((row) => (
                  <div key={row.label} className="flex items-center justify-between py-2">
                    <dt className="text-sm text-muted-foreground">{row.label}</dt>
                    <dd className="text-sm font-medium text-foreground">{row.value}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          <Card className="border-border">
            <CardHeader>
              <CardTitle className="font-serif text-xl">{t("sections.executions")}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-2xl font-semibold text-foreground">{num(stats.completed)}</div>
                  <div className="text-xs text-muted-foreground">{t("executionStats.completed")}</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold text-foreground">{num(stats.running)}</div>
                  <div className="text-xs text-muted-foreground">{t("executionStats.running")}</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold text-foreground">{num(stats.failed)}</div>
                  <div className="text-xs text-muted-foreground">{t("executionStats.failed")}</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Users */}
      <Section title={t("sections.users")} count={counts.users}>
        {data.users.length === 0 ? (
          <EmptyRow label={t("empty")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("usersTable.name")}</TableHead>
                <TableHead>{t("usersTable.email")}</TableHead>
                <TableHead>{t("usersTable.role")}</TableHead>
                <TableHead>{t("usersTable.builder")}</TableHead>
                <TableHead>{t("usersTable.status")}</TableHead>
                <TableHead>{t("usersTable.joined")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.users.map((u) => (
                <TableRow key={u.id} className="border-border">
                  <TableCell className="font-medium">{u.name}</TableCell>
                  <TableCell className="text-muted-foreground">{u.email ?? "—"}</TableCell>
                  <TableCell>
                    <Badge variant={u.is_admin ? "default" : "outline"}>
                      {u.is_admin ? t("roleAdmin") : t("roleMember")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {u.can_build_plugins ? (
                      <Badge variant="secondary">{t("canBuild")}</Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.is_active ? "default" : "secondary"}>
                      {u.is_active ? t("active") : t("inactive")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{fmtDate(u.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {/* API keys */}
      <Section title={t("sections.apiKeys")} count={counts.api_keys}>
        {data.api_keys.length === 0 ? (
          <EmptyRow label={t("empty")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("keysTable.name")}</TableHead>
                <TableHead>{t("keysTable.prefix")}</TableHead>
                <TableHead>{t("keysTable.status")}</TableHead>
                <TableHead>{t("keysTable.lastUsed")}</TableHead>
                <TableHead>{t("keysTable.created")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.api_keys.map((k) => (
                <TableRow key={k.id} className="border-border">
                  <TableCell className="font-medium">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{k.key_prefix}…</TableCell>
                  <TableCell>
                    <Badge variant={k.is_active ? "default" : "secondary"}>
                      {k.is_active ? t("active") : t("inactive")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{fmtDateTime(k.last_used_at)}</TableCell>
                  <TableCell className="text-muted-foreground">{fmtDate(k.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {/* Models */}
      <Section title={t("sections.models")} count={counts.models}>
        {data.models.length === 0 ? (
          <EmptyRow label={t("empty")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("modelsTable.name")}</TableHead>
                <TableHead>{t("modelsTable.source")}</TableHead>
                <TableHead>{t("modelsTable.executions")}</TableHead>
                <TableHead>{t("modelsTable.creditsUsed")}</TableHead>
                <TableHead>{t("modelsTable.lastRun")}</TableHead>
                <TableHead>{t("modelsTable.status")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.models.map((m) => (
                <TableRow key={m.id} className="border-border">
                  <TableCell className="font-medium">{m.display_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {m.source === "marketplace" ? t("sourceMarketplace") : t("sourceCustom")}
                    </Badge>
                  </TableCell>
                  <TableCell>{num(m.total_executions)}</TableCell>
                  <TableCell>{num(m.total_credits_used)}</TableCell>
                  <TableCell className="text-muted-foreground">{fmtDateTime(m.last_executed_at)}</TableCell>
                  <TableCell>
                    <Badge variant={m.is_active ? "default" : "secondary"}>
                      {m.is_active ? t("active") : t("inactive")}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {/* Recent executions */}
      <Section title={t("sections.executions")} note={t("recentNote", { count: RECENT_LIMIT })}>
        {data.recent_executions.length === 0 ? (
          <EmptyRow label={t("empty")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("execTable.model")}</TableHead>
                <TableHead>{t("execTable.status")}</TableHead>
                <TableHead>{t("execTable.solver")}</TableHead>
                <TableHead>{t("execTable.credits")}</TableHead>
                <TableHead>{t("execTable.objective")}</TableHead>
                <TableHead>{t("execTable.date")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent_executions.map((e) => (
                <TableRow key={e.id} className="border-border">
                  <TableCell className="font-medium">{e.model_display_name ?? "—"}</TableCell>
                  <TableCell>{statusBadge(e.status)}</TableCell>
                  <TableCell className="text-muted-foreground">{e.solver_name ?? "—"}</TableCell>
                  <TableCell>{num(e.credits_consumed)}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {e.objective_value !== null ? e.objective_value.toLocaleString(locale) : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{fmtDateTime(e.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      {/* Recent transactions */}
      <Section title={t("sections.transactions")} note={t("recentNote", { count: RECENT_LIMIT })}>
        {data.recent_transactions.length === 0 ? (
          <EmptyRow label={t("empty")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("txTable.type")}</TableHead>
                <TableHead>{t("txTable.amount")}</TableHead>
                <TableHead>{t("txTable.balance")}</TableHead>
                <TableHead>{t("txTable.description")}</TableHead>
                <TableHead>{t("txTable.date")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent_transactions.map((tx) => (
                <TableRow key={tx.id} className="border-border">
                  <TableCell>
                    <Badge variant="outline">{tx.transaction_type}</Badge>
                  </TableCell>
                  <TableCell className={tx.credits_amount < 0 ? "text-destructive" : "text-foreground"}>
                    {tx.credits_amount > 0 ? "+" : ""}
                    {num(tx.credits_amount)}
                  </TableCell>
                  <TableCell>{num(tx.balance_after)}</TableCell>
                  <TableCell className="text-muted-foreground max-w-xs truncate">{tx.description}</TableCell>
                  <TableCell className="text-muted-foreground">{fmtDateTime(tx.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>

      <div className="pt-2">{backLink}</div>
    </div>
  );
}

function Section({
  title,
  count,
  note,
  children,
}: {
  title: string;
  count?: number;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="font-serif text-xl flex items-center gap-2">
          {title}
          {count !== undefined && (
            <span className="text-sm font-normal text-muted-foreground">({count})</span>
          )}
        </CardTitle>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </CardHeader>
      <CardContent className="p-0 sm:p-0">{children}</CardContent>
    </Card>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <div className="py-8 text-center text-muted-foreground text-sm">{label}</div>;
}

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DomainSummaryEntry } from "./analytics-types";
import { DOMAIN_COLORS } from "./analytics-helpers";

interface AnalyticsDomainHealthProps {
  domains: DomainSummaryEntry[];
}

function colorForDomain(domain: string): string {
  return DOMAIN_COLORS[domain.toLowerCase()] ?? "#6b7280";
}

export function AnalyticsDomainHealth({
  domains,
}: AnalyticsDomainHealthProps) {
  const total = domains.reduce((sum, d) => sum + d.count, 0);

  if (domains.length === 0 || total === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Feature Domains</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-center text-muted-foreground py-12">
            No events recorded yet
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Feature Domains</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex h-10 rounded-lg overflow-hidden">
          {domains.map((d) => {
            const pct = (d.count / total) * 100;
            if (pct < 0.5) return null;
            return (
              <div
                key={d.domain}
                className="h-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor: colorForDomain(d.domain),
                  minWidth: pct > 0 ? "4px" : "0",
                }}
                title={`${d.domain}: ${d.count} (${pct.toFixed(1)}%)`}
              />
            );
          })}
        </div>

        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
          {domains.map((d) => {
            const pct = total > 0 ? ((d.count / total) * 100).toFixed(1) : "0";
            return (
              <div
                key={d.domain}
                className="flex items-center gap-2 text-sm"
              >
                <span
                  className="inline-block h-3 w-3 rounded-full shrink-0"
                  style={{ backgroundColor: colorForDomain(d.domain) }}
                />
                <span className="font-medium capitalize">{d.domain}</span>
                <span className="text-muted-foreground">
                  {d.count.toLocaleString()} ({pct}%)
                </span>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

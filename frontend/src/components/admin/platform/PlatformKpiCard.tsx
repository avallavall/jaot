import { Card, CardContent } from "@/components/ui/card";

interface PlatformKpiCardProps {
  label: string;
  value: string;
  hint?: string;
}

/** Compact KPI tile: label, big value, optional hint. */
export function PlatformKpiCard({ label, value, hint }: PlatformKpiCardProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

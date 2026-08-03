"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

export interface PieEntry {
  name: string;
  value: number;
  fill: string;
}

interface DistributionPieCardProps {
  title: string;
  data: PieEntry[];
  noDataLabel: string;
  formatSingle: (name: string, count: number) => string;
}

// A distribution with one category is a sentence, not a donut of one colour —
// the same sparse-data rule the author area follows. Lives outside the page
// file: Next.js rejects extra exports from a page module.
export function DistributionPieCard({
  title,
  data,
  noDataLabel,
  formatSingle,
}: DistributionPieCardProps) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <h3 className="font-semibold mb-4">{title}</h3>
      {data.length === 1 ? (
        <p className="text-sm py-6 flex items-center gap-2">
          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: data[0].fill }} />
          {formatSingle(data[0].name, data[0].value)}
        </p>
      ) : data.length > 0 ? (
        <div className="flex items-center gap-4">
          <ResponsiveContainer width="50%" height={180}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" innerRadius={40} outerRadius={70} dataKey="value">
                {data.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="space-y-2">
            {data.map((entry) => (
              <div key={entry.name} className="flex items-center gap-2 text-sm">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.fill }} />
                <span>{entry.name}</span>
                <span className="font-medium">{entry.value}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{noDataLabel}</p>
      )}
    </div>
  );
}

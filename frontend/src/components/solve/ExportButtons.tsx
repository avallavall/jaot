"use client";

import React, { useState } from "react";
import html2canvas from "html2canvas";
import { Download, FileText, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { ModelExecution } from "@/lib/types";
import { downloadCSV } from "@/lib/csv-utils";
import { extractVariables } from "@/lib/result-utils";

interface ExportButtonsProps {
  execution: ModelExecution;
  chartRef?: React.RefObject<HTMLDivElement | null>;
  trendChartRef?: React.RefObject<HTMLDivElement | null>;
}

interface ExportLabels {
  solutionReport: string;
  variableAssignments: string;
  constraintDetails: string;
  executionId: string;
  status: string;
  solverStatus: string;
  objectiveValue: string;
  creditsLabel: string;
  origin: string;
  nameHeader: string;
  typeHeader: string;
  valueHeader: string;
  lowerBound: string;
  upperBound: string;
  expression: string;
  bindingStatus: string;
  gapConvergence: string;
  objectiveTrend: string;
  generated: string;
  solveTime: string;
  creditsUsed: string;
  triggerIdLabel: string;
  noVariables: string;
  printSaveAsPdf: string;
  dateLabel: string;
  popupBlocked: string;
}

function exportSolutionCSV(execution: ModelExecution, labels: ExportLabels): void {
  const resultData = execution.result_data as Record<string, unknown> | undefined;
  const variables = extractVariables(resultData);
  const constraints =
    (execution.input_data?.constraints as { name?: string; expression?: string }[] | undefined) ??
    [];

  const rows: (string | number | null | undefined)[][] = [];

  rows.push([labels.executionId, labels.status, labels.solverStatus, labels.objectiveValue, labels.creditsLabel, labels.origin]);
  rows.push([
    execution.id,
    execution.status,
    execution.solver_status ?? "",
    execution.objective_value ?? "",
    execution.credits_consumed,
    execution.origin ?? "manual",
  ]);

  rows.push([]);

  rows.push([labels.variableAssignments]);
  rows.push([labels.nameHeader, labels.typeHeader, labels.valueHeader, labels.lowerBound, labels.upperBound]);
  for (const v of variables) {
    rows.push([v.name, v.type, v.value, "", ""]);
  }

  rows.push([]);

  rows.push([labels.constraintDetails]);
  rows.push([labels.nameHeader, labels.expression, labels.bindingStatus]);
  for (const c of constraints) {
    rows.push([c.name ?? "", c.expression ?? "", "N/A"]);
  }

  downloadCSV(`solution-${execution.id}.csv`, rows);
}

async function captureChartAsImage(
  ref: React.RefObject<HTMLDivElement | null>
): Promise<string | null> {
  if (!ref?.current) return null;
  try {
    const canvas = await html2canvas(ref.current, {
      backgroundColor: "#ffffff",
      scale: 2,
      useCORS: true,
    });
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

async function exportPDF(
  execution: ModelExecution,
  labels: ExportLabels,
  chartImageDataUrl?: string | null,
  trendChartImageDataUrl?: string | null
): Promise<void> {
  const resultData = execution.result_data as Record<string, unknown> | undefined;
  const variables = extractVariables(resultData);

  const variableRows = variables
    .map(
      (v) =>
        `<tr>
          <td><span class="var-name">${v.name}</span></td>
          <td><span class="var-type">${v.type}</span></td>
          <td class="var-value">${typeof v.value === "number" ? v.value.toLocaleString(undefined, { maximumFractionDigits: 6 }) : v.value}</td>
        </tr>`
    )
    .join("\n");

  const gapChartSection =
    chartImageDataUrl
      ? `<h2>${labels.gapConvergence}</h2>
         <img src="${chartImageDataUrl}" alt="${labels.gapConvergence}" />`
      : "";

  const trendChartSection =
    trendChartImageDataUrl
      ? `<h2>${labels.objectiveTrend}</h2>
         <img src="${trendChartImageDataUrl}" alt="${labels.objectiveTrend}" />`
      : "";

  const dateStr = new Date(execution.created_at).toLocaleString();
  const duration = execution.execution_time_ms != null ? `${execution.execution_time_ms} ms` : "\u2014";
  const credits = execution.credits_consumed;
  const objValue =
    execution.objective_value != null
      ? execution.objective_value.toLocaleString(undefined, { maximumFractionDigits: 6 })
      : "\u2014";

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>JAOT \u2014 ${labels.solutionReport}</title>
  <style>
    /* JAOT vintage palette — matches the platform theme */
    :root {
      --bg: #F6F0EA;
      --card: #FFFDF8;
      --fg: #3A3230;
      --primary: #5D4E47;
      --primary-fg: #FFFFFF;
      --accent: #8AA499;
      --muted: #F1E6D8;
      --muted-fg: #6B5F59;
      --border: rgba(93, 78, 71, 0.18);
      --label: #9B8E88;
    }
    @media print {
      .no-print { display: none !important; }
      body { margin: 0; background: #FFFFFF; }
      .meta-grid, .table-card { box-shadow: none !important; }
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Geist", "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--fg);
      margin: 0;
      padding: 40px 48px;
      background: var(--bg);
      line-height: 1.5;
    }
    .report-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 32px;
      padding-bottom: 24px;
      border-bottom: 2px solid var(--primary);
    }
    .brand {
      font-family: "Geist", Georgia, "Times New Roman", serif;
      font-size: 28px;
      font-weight: 800;
      color: var(--primary);
      letter-spacing: 0.04em;
    }
    .report-title {
      font-size: 13px;
      color: var(--muted-fg);
      margin-top: 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .header-meta {
      text-align: right;
      font-size: 12px;
      color: var(--muted-fg);
    }
    .header-meta strong { color: var(--fg); font-weight: 600; }
    .objective-banner {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 24px 28px;
      margin-bottom: 28px;
      background: var(--card);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
    }
    .objective-banner .label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted-fg);
    }
    .objective-banner .value {
      font-family: "Geist Mono", "JetBrains Mono", "Courier New", monospace;
      font-size: 32px;
      font-weight: 700;
      color: var(--primary);
      margin-top: 4px;
    }
    .objective-banner .status {
      padding: 6px 14px;
      background: var(--muted);
      border: 1px solid var(--border);
      color: var(--fg);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0;
      margin-bottom: 32px;
      background: var(--card);
      border: 1px solid var(--border);
    }
    .meta-item {
      padding: 18px 20px;
      border-right: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
    }
    .meta-item:nth-child(3n) { border-right: none; }
    .meta-grid > .meta-item:nth-last-child(-n+3) { border-bottom: none; }
    .meta-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--label);
      font-weight: 600;
    }
    .meta-value {
      font-size: 14px;
      font-weight: 600;
      color: var(--fg);
      margin-top: 4px;
      word-break: break-all;
    }
    .meta-value.mono {
      font-family: "Geist Mono", "JetBrains Mono", "Courier New", monospace;
      font-size: 12px;
    }
    h2 {
      font-size: 13px;
      font-weight: 700;
      color: var(--primary);
      margin: 32px 0 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .table-card {
      background: var(--card);
      border: 1px solid var(--border);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    thead {
      background: var(--muted);
    }
    thead th {
      padding: 12px 16px;
      text-align: left;
      font-weight: 700;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted-fg);
      border-bottom: 2px solid var(--border);
    }
    tbody td {
      padding: 8px 16px;
      border-bottom: 1px solid var(--border);
      color: var(--fg);
    }
    tbody tr:nth-child(even) td { background: rgba(241, 230, 216, 0.35); }
    tbody tr:last-child td { border-bottom: none; }
    .var-name { font-family: "Geist Mono", "JetBrains Mono", monospace; color: var(--primary); font-weight: 600; }
    .var-type {
      display: inline-block;
      padding: 2px 8px;
      background: var(--muted);
      border: 1px solid var(--border);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted-fg);
    }
    .var-value { font-family: "Geist Mono", "JetBrains Mono", monospace; text-align: right; font-weight: 600; }
    .print-btn {
      display: inline-block;
      margin-bottom: 24px;
      padding: 12px 24px;
      background: var(--primary);
      color: var(--primary-fg);
      border: none;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      cursor: pointer;
      box-shadow: 0 2px 0 rgba(58, 50, 48, 0.15);
    }
    .print-btn:hover { background: #4A3F39; }
    .footer {
      margin-top: 40px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
      font-size: 11px;
      color: var(--label);
      text-align: center;
      letter-spacing: 0.04em;
    }
    img { max-width: 100%; border: 1px solid var(--border); margin-top: 12px; }
  </style>
</head>
<body>
  <button class="no-print print-btn" onclick="window.print()">${labels.printSaveAsPdf}</button>

  <div class="report-header">
    <div>
      <div class="brand">JAOT</div>
      <div class="report-title">${labels.solutionReport}</div>
    </div>
    <div class="header-meta">
      <div>${labels.generated}</div>
      <div><strong>${new Date().toLocaleString()}</strong></div>
    </div>
  </div>

  <div class="objective-banner">
    <div>
      <div class="label">${labels.objectiveValue}</div>
      <div class="value">${objValue}</div>
    </div>
    <div class="status">${execution.solver_status ?? "\u2014"}</div>
  </div>

  <div class="meta-grid">
    <div class="meta-item">
      <div class="meta-label">${labels.executionId}</div>
      <div class="meta-value mono">${execution.id}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">${labels.dateLabel}</div>
      <div class="meta-value">${dateStr}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">${labels.solveTime}</div>
      <div class="meta-value">${duration}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">${labels.creditsUsed}</div>
      <div class="meta-value">${credits}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">${labels.origin}</div>
      <div class="meta-value">${execution.origin ?? "manual"}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">${labels.solverStatus}</div>
      <div class="meta-value">${execution.solver_status ?? "\u2014"}</div>
    </div>
    ${execution.trigger_id ? `<div class="meta-item">
      <div class="meta-label">${labels.triggerIdLabel}</div>
      <div class="meta-value mono">${execution.trigger_id}</div>
    </div>` : ""}
  </div>

  <h2>${labels.variableAssignments}</h2>
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>${labels.nameHeader}</th>
          <th>${labels.typeHeader}</th>
          <th style="text-align:right;">${labels.valueHeader}</th>
        </tr>
      </thead>
      <tbody>
        ${variableRows || `<tr><td colspan="3" style="padding:24px 16px;color:var(--label);text-align:center;font-style:italic;">${labels.noVariables}</td></tr>`}
      </tbody>
    </table>
  </div>

  ${gapChartSection}
  ${trendChartSection}

  <div class="footer">
    JAOT \u00B7 Optimization Platform \u00B7 ${new Date().getFullYear()}
  </div>
</body>
</html>`;

  // Open in new tab via Blob URL — avoids popup-blocker issues. Falls back to direct download.
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank");
  if (!win) {
    const a = document.createElement("a");
    a.href = url;
    a.download = `solution-report-${execution.id}.html`;
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function ExportButtons({ execution, chartRef, trendChartRef }: ExportButtonsProps) {
  const t = useTranslations("solve.export");
  const [pdfLoading, setPdfLoading] = useState(false);

  const labels: ExportLabels = {
    solutionReport: t("solutionReport"),
    variableAssignments: t("variableAssignments"),
    constraintDetails: t("constraintDetails"),
    executionId: t("executionId"),
    status: t("status"),
    solverStatus: t("solverStatus"),
    objectiveValue: t("objectiveValue"),
    creditsLabel: t("creditsLabel"),
    origin: t("origin"),
    nameHeader: t("nameHeader"),
    typeHeader: t("typeHeader"),
    valueHeader: t("valueHeader"),
    lowerBound: t("lowerBound"),
    upperBound: t("upperBound"),
    expression: t("expression"),
    bindingStatus: t("bindingStatus"),
    gapConvergence: t("gapConvergence"),
    objectiveTrend: t("objectiveTrend"),
    generated: t("generated"),
    solveTime: t("solveTime"),
    creditsUsed: t("creditsUsed"),
    triggerIdLabel: t("triggerIdLabel"),
    noVariables: t("noVariables"),
    printSaveAsPdf: t("printSaveAsPdf"),
    dateLabel: t("dateLabel"),
    popupBlocked: t("popupBlocked"),
  };

  const handleExportCSV = () => {
    exportSolutionCSV(execution, labels);
  };

  const handleExportPDF = async () => {
    setPdfLoading(true);
    try {
      const chartImg = chartRef ? await captureChartAsImage(chartRef) : null;
      const trendImg = trendChartRef ? await captureChartAsImage(trendChartRef) : null;
      await exportPDF(execution, labels, chartImg, trendImg);
    } finally {
      setPdfLoading(false);
    }
  };

  const handleServerExport = async (fmt: string) => {
    try {
      const blob = await api.fileExport.download(execution.id, fmt);
      const filename = `${execution.id}.${fmt}`;
      const a = document.createElement("a");
      const blobUrl = URL.createObjectURL(blob);
      a.href = blobUrl;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
    } catch {
      toast.error(t("downloadFailed"));
    }
  };

  const modelFormats = [
    { key: "mps", label: t("mps") },
    { key: "lp", label: t("lp") },
    { key: "cip", label: t("cip") },
    { key: "sol", label: t("sol") },
    { key: "json", label: t("json") },
  ];

  return (
    <>
      <Button variant="outline" size="sm" onClick={handleExportCSV}>
        <Download className="h-4 w-4 mr-2" />
        {t("csv")}
      </Button>
      <Button variant="outline" size="sm" onClick={handleExportPDF} disabled={pdfLoading}>
        <FileText className="h-4 w-4 mr-2" />
        {pdfLoading ? t("generating") : t("pdf")}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Download className="h-4 w-4 mr-2" />
            {t("downloadModel")}
            <ChevronDown className="h-3 w-3 ml-1" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {modelFormats.map(({ key, label }) => (
            <DropdownMenuItem key={key} onClick={() => handleServerExport(key)}>
              {label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}

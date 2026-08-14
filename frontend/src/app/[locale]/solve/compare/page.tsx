"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Play, Upload, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ComparisonTable } from "@/components/solve/compare/ComparisonTable";
import { canStop, shouldKeepPolling } from "@/components/solve/compare/polling";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSolvers } from "@/hooks/useSolvers";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { ACCEPTED_EXTENSIONS, isAcceptedFile } from "@/lib/file-import";
import type { ComparisonDetail, ProjectListItem } from "@/lib/types";

/** How often the table refreshes while the comparison is still running. The
 * solves are sequential, so nothing changes faster than one solver at a time. */
const POLL_INTERVAL_MS = 2000;

export default function SolverComparePage() {
  const t = useTranslations("solverCompare");
  const { availableSolvers, solversLoading } = useSolvers();

  const [source, setSource] = useState<"model" | "file">("model");
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [uploaded, setUploaded] = useState<{ problem: unknown; filename: string } | null>(null);
  const [uploading, setUploading] = useState(false);

  const [selected, setSelected] = useState<string[]>([]);
  const [timeLimit, setTimeLimit] = useState(60);
  const [gapTolerance, setGapTolerance] = useState(0.0001);

  const [comparison, setComparison] = useState<ComparisonDetail | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api
      .listProjects({ mine: true, limit: 100 })
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  // Pre-select every solver that can run, so the common case is one click. The
  // server decides which of them actually can; this is only a starting point.
  useEffect(() => {
    if (selected.length === 0 && availableSolvers.length > 0) {
      setSelected(availableSolvers.filter((s) => s.available).map((s) => s.name));
    }
  }, [availableSolvers, selected.length]);

  const refresh = useCallback(async (id: string) => {
    try {
      setComparison(await api.solverComparison.get(id));
    } catch {
      // A dropped poll is not worth an error toast — the next tick retries.
    }
  }, []);

  // Poll only while there is something left to happen — which outlasts the
  // comparison's own status: stopping one leaves the solve already inside a
  // solver to finish and write its verdict. See shouldKeepPolling.
  const comparisonId = comparison?.id;
  const polling = shouldKeepPolling(comparison);
  const stoppable = canStop(comparison);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!comparisonId || !polling) return;
    const timer = setInterval(() => {
      void refreshRef.current(comparisonId);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [comparisonId, polling]);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    if (!isAcceptedFile(file)) {
      toast.error(t("setup.fileRejected", { extensions: ACCEPTED_EXTENSIONS.join(", ") }));
      return;
    }
    setUploading(true);
    try {
      const preview = await api.fileImport.preview(file);
      setUploaded({ problem: preview.problem, filename: file.name });
    } catch (error) {
      toast.error(getErrorMessage(error, t("setup.fileFailed")));
    } finally {
      setUploading(false);
    }
  }

  async function start() {
    setStarting(true);
    try {
      const created = await api.solverComparison.create({
        solver_names: selected,
        settings: { time_limit_seconds: timeLimit, gap_tolerance: gapTolerance },
        ...(source === "model"
          ? { project_id: projectId }
          : { problem: uploaded?.problem, uploaded_filename: uploaded?.filename }),
      });
      setComparison(created);
    } catch (error) {
      toast.error(getErrorMessage(error, t("results.startFailed")));
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!comparison) return;
    try {
      setComparison(await api.solverComparison.cancel(comparison.id));
    } catch (error) {
      toast.error(getErrorMessage(error, t("results.cancelFailed")));
    }
  }

  const hasProblem = source === "model" ? Boolean(projectId) : Boolean(uploaded);
  const canStart = hasProblem && selected.length > 0 && !starting;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>{t("setup.title")}</CardTitle>
          <CardDescription>{t("setup.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-3">
            <Label>{t("setup.sourceLabel")}</Label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={source === "model" ? "default" : "outline"}
                onClick={() => setSource("model")}
              >
                {t("setup.sourceModel")}
              </Button>
              <Button
                type="button"
                variant={source === "file" ? "default" : "outline"}
                onClick={() => setSource("file")}
              >
                {t("setup.sourceFile")}
              </Button>
            </div>

            {source === "model" ? (
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger className="max-w-md">
                  <SelectValue placeholder={t("setup.modelPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={project.id}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <div className="space-y-2">
                <label className="flex max-w-md cursor-pointer items-center gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground hover:bg-accent">
                  {uploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  <span>{uploaded ? uploaded.filename : t("setup.filePlaceholder")}</span>
                  <input
                    type="file"
                    className="sr-only"
                    accept={ACCEPTED_EXTENSIONS.join(",")}
                    onChange={(e) => void handleFile(e.target.files?.[0])}
                  />
                </label>
                {/* The upload is thrown away with the comparison — saying so up
                    front is cheaper than a support question later. */}
                <p className="text-xs text-muted-foreground">{t("setup.fileThrowaway")}</p>
              </div>
            )}
          </div>

          <div className="space-y-3">
            <Label>{t("setup.solversLabel")}</Label>
            {solversLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <div className="flex flex-wrap gap-4">
                {availableSolvers
                  .filter((solver) => solver.available)
                  .map((solver) => (
                    <label key={solver.name} className="flex items-center gap-2 text-sm">
                      <Checkbox
                        checked={selected.includes(solver.name)}
                        onCheckedChange={(checked) =>
                          setSelected((current) =>
                            checked
                              ? [...current, solver.name]
                              : current.filter((n) => n !== solver.name),
                          )
                        }
                      />
                      <span className="uppercase">{solver.name}</span>
                    </label>
                  ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-4">
            <div className="space-y-2">
              <Label htmlFor="time-limit">{t("setup.timeLimitLabel")}</Label>
              <Input
                id="time-limit"
                type="number"
                min={1}
                className="w-40"
                value={timeLimit}
                onChange={(e) => setTimeLimit(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gap">{t("setup.gapLabel")}</Label>
              <Input
                id="gap"
                type="number"
                min={0}
                max={1}
                step={0.0001}
                className="w-40"
                value={gapTolerance}
                onChange={(e) => setGapTolerance(Number(e.target.value))}
              />
            </div>
          </div>

          {/* The wait is the sum, not the maximum: the solvers run one after
              another so their seconds stay comparable. */}
          <p className="text-sm text-muted-foreground">
            {t("setup.estimate", { seconds: timeLimit * Math.max(selected.length, 1) })}
          </p>

          <Button onClick={() => void start()} disabled={!canStart}>
            {starting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            {t("setup.start")}
          </Button>
        </CardContent>
      </Card>

      {comparison ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle>{comparison.problem_name ?? t("results.title")}</CardTitle>
              <CardDescription>{t(`comparisonStatus.${comparison.status}`)}</CardDescription>
            </div>
            {stoppable ? (
              <Button variant="outline" onClick={() => void cancel()}>
                <X className="mr-2 h-4 w-4" />
                {t("results.cancel")}
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            <ComparisonTable comparison={comparison} />
            {comparison.error_message ? (
              <p className="mt-4 text-sm text-destructive">{comparison.error_message}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

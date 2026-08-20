"use client";

import { useState, useEffect } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import type {
  CreateTriggerRequest,
  OverrideField,
  ProjectListItem,
  ProjectVersionSummary,
} from "@/lib/types";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { OverrideSchemaEditor } from "./OverrideSchemaEditor";
import { Loader2 } from "lucide-react";
import Link from "next/link";

interface TriggerFormProps {
  onSuccess: (triggerId: string, triggerSecret: string) => void;
  workspaceId?: string;
}

export function TriggerForm({ onSuccess, workspaceId }: TriggerFormProps) {
  const canEdit = useWorkspacePermission("editor");
  const roleName = useRoleDisplayName();
  const t = useTranslations("triggers.form");
  const tError = useTranslations("errors.codes");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [overrideSchema, setOverrideSchema] = useState<OverrideField[]>([]);

  // Studio projects, not builder documents: the studio is where models are built
  // since the P1.5 fusion, and it never creates a builder document — so a form
  // that listed those could not automate anything anyone had made.
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [versions, setVersions] = useState<ProjectVersionSummary[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");

  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Load the organisation's studio models on mount. Only committed ones can be
  // pinned: a trigger fires an immutable version, never the mutable draft.
  useEffect(() => {
    const load = async () => {
      setLoadingDocs(true);
      try {
        const all = await api.listProjects({ status: "active" }, workspaceId);
        setProjects(all.filter((p) => p.committed_count > 0));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("loadModelsError"));
      } finally {
        setLoadingDocs(false);
      }
    };
    load();
  }, [workspaceId, t]);

  // Load versions when document changes
  useEffect(() => {
    if (!selectedProjectId) {
      setVersions([]);
      setSelectedVersionId("");
      return;
    }
    const load = async () => {
      setLoadingVersions(true);
      setSelectedVersionId("");
      try {
        const vers = await api.listProjectVersions(selectedProjectId, { limit: 50 }, workspaceId);
        setVersions(vers);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("loadVersionsError"));
      } finally {
        setLoadingVersions(false);
      }
    };
    load();
  }, [selectedProjectId, workspaceId, t]);

  const validateUrl = (url: string) => {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      toast.error(t("nameRequired"));
      return;
    }
    if (!selectedProjectId) {
      toast.error(t("selectModelError"));
      return;
    }
    if (!selectedVersionId) {
      toast.error(t("selectVersionError"));
      return;
    }
    if (!webhookUrl.trim()) {
      toast.error(t("webhookRequired"));
      return;
    }
    if (!validateUrl(webhookUrl)) {
      toast.error(t("webhookInvalid"));
      return;
    }

    setSubmitting(true);
    try {
      const body: CreateTriggerRequest = {
        name: name.trim(),
        description: description.trim() || undefined,
        model_project_id: selectedProjectId,
        model_project_version_id: selectedVersionId,
        webhook_url: webhookUrl.trim(),
        webhook_secret: webhookSecret.trim() || undefined,
        override_schema: overrideSchema.length > 0 ? overrideSchema : undefined,
        workspace_id: workspaceId || undefined,
      };
      const result = await api.triggers.create(body, workspaceId);
      toast.success(t("createdSuccess"));
      onSuccess(result.id, result.trigger_secret);
    } catch (err) {
      // The API's `detail` is English by contract. A refusal that names
      // itself, like a webhook address the server cannot reach, is
      // rendered from its code instead.
      toast.error(
        translateApiError(err, tError, err instanceof Error ? err.message : t("createError")),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-4">
        <h2 className="text-base font-semibold">{t("basicInfo")}</h2>
        <div className="space-y-2">
          <Label htmlFor="trigger-name">{t("nameLabel")}</Label>
          <Input
            id="trigger-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("namePlaceholder")}
            required
            disabled={!canEdit}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="trigger-description">{t("descriptionLabel")}</Label>
          <Textarea
            id="trigger-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("descriptionPlaceholder")}
            rows={2}
            disabled={!canEdit}
          />
        </div>
      </div>

      <div className="space-y-4">
        <h2 className="text-base font-semibold">{t("pinnedVersion")}</h2>
        <div className="space-y-2">
          <Label>{t("modelLabel")}</Label>
          {loadingDocs ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t("loadingModels")}
            </div>
          ) : projects.length === 0 ? (
            /* Points at the studio, not the retired /builder. The list is
               already narrowed to models with a commit, so "none yet" here also
               covers "you have models but none is committed" — which is why the
               copy talks about committing, not only about creating. */
            <p className="text-sm text-muted-foreground">
              {t.rich("noModels", {
                link: (chunks) => (
                  <Link href="/studio" className="text-primary underline">{chunks}</Link>
                ),
              })}
            </p>
          ) : (
            <Select value={selectedProjectId} onValueChange={setSelectedProjectId} disabled={!canEdit}>
              <SelectTrigger>
                <SelectValue placeholder={t("selectModel")} />
              </SelectTrigger>
              <SelectContent>
                {projects.map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {selectedProjectId && (
          <div className="space-y-2">
            <Label>{t("versionLabel")}</Label>
            {loadingVersions ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("loadingVersions")}
              </div>
            ) : versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("noVersions")}
              </p>
            ) : (
              <Select value={selectedVersionId} onValueChange={setSelectedVersionId} disabled={!canEdit}>
                <SelectTrigger>
                  <SelectValue placeholder={t("selectVersion")} />
                </SelectTrigger>
                <SelectContent>
                  {versions.map((ver) => (
                    <SelectItem key={ver.id} value={ver.id}>
                      {/* A committed version always carries its message \u2014 the
                          studio makes it mandatory \u2014 so there is no unnamed
                          case to fall back from, unlike builder snapshots. */}
                      {`v${ver.sequence} \u00b7 ${ver.commit_summary}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        )}
      </div>

      <div className="space-y-4">
        <h2 className="text-base font-semibold">{t("webhookConfig")}</h2>
        <div className="space-y-2">
          <Label htmlFor="webhook-url">{t("webhookUrlLabel")}</Label>
          <Input
            id="webhook-url"
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder={t("webhookUrlPlaceholder")}
            required
            disabled={!canEdit}
          />
          <p className="text-xs text-muted-foreground">
            {t("webhookUrlHelp")}
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="webhook-secret">{t("webhookSecretLabel")}</Label>
          <Input
            id="webhook-secret"
            value={webhookSecret}
            onChange={(e) => setWebhookSecret(e.target.value)}
            placeholder={t("webhookSecretPlaceholder")}
            disabled={!canEdit}
          />
          <p className="text-xs text-muted-foreground">
            {t("webhookSecretHelp")}
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <h2 className="text-base font-semibold">{t("overrideSchemaTitle")}</h2>
        <OverrideSchemaEditor value={overrideSchema} onChange={setOverrideSchema} />
      </div>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="w-full">
              <Button type="submit" disabled={submitting || !canEdit} className="w-full">
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {t("creating")}
                  </>
                ) : (
                  t("createButton")
                )}
              </Button>
            </span>
          </TooltipTrigger>
          {!canEdit && (
            <TooltipContent className="max-w-xs text-center">
              {t("noPermission", { role: roleName })}
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
    </form>
  );
}

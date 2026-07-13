"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { ModelCatalogItem, ProjectRead } from "@/lib/types";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useDialog } from "@/components/ui/dialog-custom";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Upload, ExternalLink, Loader2, GitCommitHorizontal } from "lucide-react";
import { RichTextEditor } from "@/components/publish/RichTextEditor";
import { LogoUpload } from "@/components/publish/LogoUpload";
import { ScreenshotUpload } from "@/components/publish/ScreenshotUpload";

const CATEGORY_IDS = [
  "finance",
  "logistics",
  "manufacturing",
  "agriculture",
  "healthcare",
  "hr",
  "general",
];

/**
 * Publish a ModelProject to the marketplace (P1.5 fusion): the POST upserts the
 * project's listing facet and pins its latest committed version — the marketplace
 * never sees the working draft. The same page edits an already-published listing
 * (the endpoint is an upsert; the listing id IS the project id). Media uploads
 * operate on the listing, which only exists after the first publish, so they are
 * enabled in edit mode only.
 */
export default function StudioPublishPage() {
  const t = useTranslations("solve.publish");
  const { categoryLabel } = useCommonLabels();
  const params = useParams();
  const router = useRouter();
  const dialog = useDialog();
  const projectId = params.modelId as string;

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [listing, setListing] = useState<ModelCatalogItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form fields
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [shortDescription, setShortDescription] = useState("");
  const [category, setCategory] = useState("general");
  const [tags, setTags] = useState("");

  // Section fields
  const [sectionOverview, setSectionOverview] = useState("");
  const [sectionFeatures, setSectionFeatures] = useState("");
  const [sectionHowItWorks, setSectionHowItWorks] = useState("");
  const [sectionExampleIo, setSectionExampleIo] = useState("");
  const [sectionChangelog, setSectionChangelog] = useState("");

  // Media (edit mode only — the listing must exist first)
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [screenshots, setScreenshots] = useState<string[]>([]);

  const isEditMode = listing !== null;
  const canPublish = (project?.committed_count ?? 0) > 0;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const proj = await api.getProject(projectId);
        if (cancelled) return;
        setProject(proj);
        setDisplayName(proj.name || "");
        setDescription(proj.description || "");

        // An existing listing (the id IS the project id) switches to edit mode.
        try {
          const existing = await api.getCatalogModel(projectId);
          if (cancelled) return;
          setListing(existing);
          setDisplayName(existing.display_name || proj.name || "");
          setDescription(existing.description || proj.description || "");
          setShortDescription(existing.short_description || "");
          setCategory(existing.category || "general");
          setTags((existing.tags || []).join(", "));
          setSectionOverview(existing.section_overview || "");
          setSectionFeatures(existing.section_features || "");
          setSectionHowItWorks(existing.section_how_it_works || "");
          setSectionExampleIo(existing.section_example_io || "");
          setSectionChangelog(existing.section_changelog || "");
          setLogoUrl(existing.logo_url || null);
          setScreenshots(existing.screenshot_urls || []);
        } catch {
          // 404 → not published yet: first-publish mode.
        }
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, t("failedToLoad")));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const executePublish = async () => {
    setPublishing(true);
    try {
      await api.publishModel(projectId, {
        display_name: displayName.trim(),
        description: description.trim(),
        short_description: shortDescription.trim() || undefined,
        category,
        tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
        section_overview: sectionOverview.trim() || undefined,
        section_features: sectionFeatures.trim() || undefined,
        section_how_it_works: sectionHowItWorks.trim() || undefined,
        section_example_io: sectionExampleIo.trim() || undefined,
        section_changelog: sectionChangelog.trim() || undefined,
      });

      if (isEditMode) {
        toast.success(t("listingUpdated"));
      } else {
        toast.success(t("publishedSuccess"));
        router.push(`/marketplace/${projectId}`);
      }
    } catch (err) {
      const status = getErrorStatus(err);
      let msg: string;
      if (status === 400) {
        // The backend refuses to publish a project with no committed version.
        msg = t("commitFirstHelp");
      } else if (status === 422) {
        msg = t("validationFailed", { detail: getErrorMessage(err, t("failedToPublish")) });
      } else {
        msg = getErrorMessage(err, t("failedToPublish"));
      }
      dialog.showError(msg);
    } finally {
      setPublishing(false);
    }
  };

  const handlePublish = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!displayName.trim() || !description.trim()) {
      dialog.showError(t("fillRequiredFields"));
      return;
    }

    if (isEditMode) {
      executePublish();
      return;
    }

    const confirmed = await dialog.confirm(
      t("confirmPublishMessage"),
      t("confirmPublishTitle")
    );
    if (confirmed) {
      executePublish();
    }
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="flex justify-center py-12" aria-busy="true">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="container mx-auto px-4 py-8">
          <div className="p-4 bg-destructive/10 text-destructive rounded-lg mb-4">
            {error || t("failedToLoad")}
          </div>
          <Button onClick={() => router.push("/studio")}>{t("backToModels")}</Button>
        </div>
      </div>
    );
  }

  // A never-committed project cannot publish — the listing pins a committed
  // version, never the dirty draft. Send the user to commit first.
  if (!canPublish && !isEditMode) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="container mx-auto px-4 py-8 max-w-3xl">
          <div className="bg-card border rounded-lg p-8 text-center">
            <GitCommitHorizontal className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <h1 className="text-2xl font-bold text-foreground mb-2">
              {t("commitFirstTitle")}
            </h1>
            <p className="text-muted-foreground mb-8">{t("commitFirstHelp")}</p>
            <Button
              size="lg"
              data-testid="studio-publish-commit-first"
              onClick={() => router.push(`/studio/${projectId}/build`)}
            >
              {t("goToBuild")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="container mx-auto px-4 py-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-3">
          <Upload className="w-8 h-8 text-primary" />
          {isEditMode ? t("editModelPage") : t("title")}
        </h1>
        <p className="text-muted-foreground">
          {isEditMode ? t("editModelPageSubtitle") : t("subtitle")}
        </p>
      </div>

      {!isEditMode && (
        <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg">
          <p className="text-sm text-blue-800 dark:text-blue-200">{t("publishPinsVersion")}</p>
        </div>
      )}

      <form onSubmit={handlePublish} className="space-y-6" data-testid="studio-publish-form">
        <div>
          <label className="block text-sm font-medium mb-2">
            {t("displayName")} <span className="text-destructive">{t("required")}</span>
          </label>
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={t("displayNamePlaceholder")}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">{t("shortDescription")}</label>
          <Input
            value={shortDescription}
            onChange={(e) => setShortDescription(e.target.value)}
            placeholder={t("shortDescriptionPlaceholder")}
            maxLength={200}
          />
          <p className="text-xs text-muted-foreground mt-1">{t("shortDescriptionHelp")}</p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">
            {t("fullDescription")} <span className="text-destructive">{t("required")}</span>
          </label>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("fullDescriptionPlaceholder")}
            className="min-h-[150px]"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">{t("category")}</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full px-3 py-2 rounded-md border bg-background"
          >
            {CATEGORY_IDS.map((id) => (
              <option key={id} value={id}>
                {categoryLabel(id)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">{t("tags")}</label>
          <Input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder={t("tagsPlaceholder")}
          />
        </div>

        {/* Media operates on the listing, which exists only after the first publish. */}
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-2">{t("images")}</h2>
          {!isEditMode && (
            <p className="text-sm text-muted-foreground mb-4">{t("imagesAfterPublish")}</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-6">
            <LogoUpload
              modelId={isEditMode ? projectId : ""}
              logoUrl={logoUrl}
              onLogoChange={setLogoUrl}
              disabled={!isEditMode}
            />
            <ScreenshotUpload
              modelId={isEditMode ? projectId : ""}
              screenshots={screenshots}
              onScreenshotsChange={setScreenshots}
              disabled={!isEditMode}
            />
          </div>
        </div>

        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-2">{t("modelPageContent")}</h2>
          <p className="text-sm text-muted-foreground mb-4">{t("modelPageContentHelp")}</p>
          <Tabs defaultValue="overview">
            <TabsList className="mb-4">
              <TabsTrigger value="overview">{t("tabOverview")}</TabsTrigger>
              <TabsTrigger value="features">{t("tabFeatures")}</TabsTrigger>
              <TabsTrigger value="howItWorks">{t("tabHowItWorks")}</TabsTrigger>
              <TabsTrigger value="exampleIo">{t("tabExampleIo")}</TabsTrigger>
              <TabsTrigger value="changelog">{t("tabChangelog")}</TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <RichTextEditor
                content={sectionOverview}
                onChange={setSectionOverview}
                placeholder={t("overviewPlaceholder")}
              />
            </TabsContent>
            <TabsContent value="features">
              <RichTextEditor
                content={sectionFeatures}
                onChange={setSectionFeatures}
                placeholder={t("featuresPlaceholder")}
              />
            </TabsContent>
            <TabsContent value="howItWorks">
              <RichTextEditor
                content={sectionHowItWorks}
                onChange={setSectionHowItWorks}
                placeholder={t("howItWorksPlaceholder")}
              />
            </TabsContent>
            <TabsContent value="exampleIo">
              <RichTextEditor
                content={sectionExampleIo}
                onChange={setSectionExampleIo}
                placeholder={t("exampleIoPlaceholder")}
              />
            </TabsContent>
            <TabsContent value="changelog">
              <RichTextEditor
                content={sectionChangelog}
                onChange={setSectionChangelog}
                placeholder={t("changelogPlaceholder")}
              />
            </TabsContent>
          </Tabs>
        </div>

        <div className="flex flex-wrap gap-4 pt-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.push(`/studio/${projectId}/build`)}
          >
            {t("cancel")}
          </Button>
          {isEditMode && (
            <Link href={`/marketplace/${projectId}`}>
              <Button type="button" variant="outline">
                <ExternalLink className="w-4 h-4 mr-2" />
                {t("viewInMarketplace")}
              </Button>
            </Link>
          )}
          <Button
            type="submit"
            disabled={publishing}
            className="flex-1"
            data-testid="studio-publish-submit"
          >
            {publishing ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {isEditMode ? t("updating") : t("publishing")}
              </>
            ) : (
              <>
                <Upload className="w-4 h-4 mr-2" />
                {isEditMode ? t("updateListing") : t("publishToMarketplace")}
              </>
            )}
          </Button>
        </div>
      </form>

      <dialog.DialogComponent />
      </div>
    </div>
  );
}

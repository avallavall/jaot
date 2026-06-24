"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, OrganizationModel } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useDialog } from "@/components/ui/dialog-custom";
import { useTranslations } from "next-intl";
import { Upload, ArrowLeft, ExternalLink, Loader2, Save, CheckCircle, Eye, Pencil } from "lucide-react";
import { RichTextEditor } from "@/components/publish/RichTextEditor";
import { LogoUpload } from "@/components/publish/LogoUpload";
import { ScreenshotUpload } from "@/components/publish/ScreenshotUpload";

const CATEGORIES = [
  { id: "finance", label: "Finance" },
  { id: "logistics", label: "Logistics" },
  { id: "manufacturing", label: "Manufacturing" },
  { id: "agriculture", label: "Agriculture" },
  { id: "healthcare", label: "Healthcare" },
  { id: "hr", label: "HR" },
  { id: "general", label: "General" },
];

export default function PublishModelPage() {
  const t = useTranslations("solve.publish");
  const params = useParams();
  const router = useRouter();
  const dialog = useDialog();
  const modelId = params.modelId as string;

  const [model, setModel] = useState<OrganizationModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [savingSections, setSavingSections] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [publishedCatalogId, setPublishedCatalogId] = useState<string | null>(null);

  // Form fields (publish mode)
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [shortDescription, setShortDescription] = useState("");
  const [category, setCategory] = useState("general");
  const [tags, setTags] = useState("");
  const [priceEur, setPriceEur] = useState("0");

  // Section fields (both modes)
  const [sectionOverview, setSectionOverview] = useState("");
  const [sectionFeatures, setSectionFeatures] = useState("");
  const [sectionHowItWorks, setSectionHowItWorks] = useState("");
  const [sectionExampleIo, setSectionExampleIo] = useState("");
  const [sectionChangelog, setSectionChangelog] = useState("");

  // Image state (edit mode)
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [screenshots, setScreenshots] = useState<string[]>([]);

  // Derived state
  const isEditMode = !!model?.catalog_id;
  const catalogId = model?.catalog_id;

  useEffect(() => {
    loadModel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId]);

  const loadModel = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getMyModel(modelId);
      setModel(data);

      // Pre-fill form with existing data
      setDisplayName(data.display_name || data.custom_name || "");
      setDescription(data.description || "");
      // credits_per_execution removed — credits calculated dynamically

      // If already published, fetch catalog data for edit mode
      if (data.catalog_id) {
        try {
          const catalog = await api.getCatalogModel(data.catalog_id);

          // Pre-populate sections from catalog data
          setSectionOverview(catalog.section_overview || "");
          setSectionFeatures(catalog.section_features || "");
          setSectionHowItWorks(catalog.section_how_it_works || "");
          setSectionExampleIo(catalog.section_example_io || "");
          setSectionChangelog(catalog.section_changelog || "");

          // Pre-populate images
          setLogoUrl(catalog.logo_url || null);
          setScreenshots(catalog.screenshot_urls || []);
        } catch {
          setError(t("failedToLoad"));
        }
      }
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const executePublish = async () => {
    setPublishing(true);
    try {
      const catalogItem = await api.publishModel(modelId, {
        display_name: displayName.trim(),
        description: description.trim(),
        short_description: shortDescription.trim() || undefined,
        category,
        tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
        price_eur: parseFloat(priceEur) || 0,
        // credits_per_execution removed — calculated dynamically
        // Include section content in publish request
        section_overview: sectionOverview.trim() || undefined,
        section_features: sectionFeatures.trim() || undefined,
        section_how_it_works: sectionHowItWorks.trim() || undefined,
        section_example_io: sectionExampleIo.trim() || undefined,
        section_changelog: sectionChangelog.trim() || undefined,
      });

      setPublishedCatalogId(catalogItem.id);
      setPublishSuccess(true);
    } catch (err) {
      const status = getErrorStatus(err);
      let msg: string;
      if (status === 422) {
        msg = t("validationFailed", { detail: getErrorMessage(err, t("failedToPublish")) });
      } else if (status === 409) {
        msg = t("alreadyCatalogModel");
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

    // Show confirmation modal before publishing
    const confirmed = await dialog.confirm(
      t("confirmPublishMessage"),
      t("confirmPublishTitle")
    );
    if (confirmed) {
      executePublish();
    }
  };

  const handleSaveSections = async () => {
    if (!catalogId) return;

    setSavingSections(true);
    try {
      await api.request(`/api/v2/models/catalog/${catalogId}/sections`, {
        method: "PUT",
        body: JSON.stringify({
          section_overview: sectionOverview.trim() || undefined,
          section_features: sectionFeatures.trim() || undefined,
          section_how_it_works: sectionHowItWorks.trim() || undefined,
          section_example_io: sectionExampleIo.trim() || undefined,
          section_changelog: sectionChangelog.trim() || undefined,
        }),
      });
      dialog.showSuccess(t("sectionsSaved"));
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("sectionsSaveFailed")));
    } finally {
      setSavingSections(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (error && !model) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg mb-4">
          {error}
        </div>
        <Button onClick={() => router.push("/solve")}>
          {t("backToModels")}
        </Button>
      </div>
    );
  }

  if (publishSuccess) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-3xl">
        <div className="bg-card border rounded-lg p-8 text-center">
          <CheckCircle className="w-16 h-16 text-green-600 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-foreground mb-2">
            {t("published")}
          </h1>
          <p className="text-muted-foreground mb-8">
            {t("publishedSuccess")}
          </p>

          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            {publishedCatalogId && (
              <Link href={`/marketplace/${publishedCatalogId}`}>
                <Button size="lg" className="w-full sm:w-auto">
                  <Eye className="w-4 h-4 mr-2" />
                  {t("viewInMarketplace")}
                </Button>
              </Link>
            )}
            <Button
              variant="outline"
              size="lg"
              onClick={() => {
                setPublishSuccess(false);
                loadModel();
              }}
            >
              <Pencil className="w-4 h-4 mr-2" />
              {t("continueEditing")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (isEditMode && catalogId) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-3xl">
        <Link
          href="/solve"
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          {t("backToModels")}
        </Link>

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-3">
            <Upload className="w-8 h-8 text-primary" />
            {t("editModelPage")}
          </h1>
          <p className="text-muted-foreground">
            {t("editModelPageSubtitle")}
          </p>
        </div>

        <div className="bg-card border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">{t("images")}</h2>
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-6">
            <LogoUpload
              modelId={catalogId}
              logoUrl={logoUrl}
              onLogoChange={setLogoUrl}
            />
            <ScreenshotUpload
              modelId={catalogId}
              screenshots={screenshots}
              onScreenshotsChange={setScreenshots}
            />
          </div>
        </div>

        <div className="bg-card border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold mb-2">{t("contentSections")}</h2>
          <p className="text-sm text-muted-foreground mb-4">
            {t("modelPageContentHelp")}
          </p>
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

          <div className="mt-4">
            <Button onClick={handleSaveSections} disabled={savingSections}>
              {savingSections ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  {t("savingSections")}
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" />
                  {t("saveSections")}
                </>
              )}
            </Button>
          </div>
        </div>

        <div className="flex gap-4">
          <Link href={`/marketplace/${catalogId}`}>
            <Button variant="outline">
              <ExternalLink className="w-4 h-4 mr-2" />
              {t("viewInMarketplace")}
            </Button>
          </Link>
        </div>

        <dialog.DialogComponent />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-3xl">
      <Link
        href="/solve"
        className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        {t("backToModels")}
      </Link>

      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-3">
          <Upload className="w-8 h-8 text-primary" />
          {t("title")}
        </h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg">
        <p className="text-sm text-blue-800 dark:text-blue-200">
          {t("publishInfoText")}
        </p>
      </div>

      <form onSubmit={handlePublish} className="space-y-6">
        <div>
          <label className="block text-sm font-medium mb-2">
            {t("displayName")}{" "}
            <span className="text-destructive">{t("required")}</span>
          </label>
          <Input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={t("displayNamePlaceholder")}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">
            {t("shortDescription")}
          </label>
          <Input
            value={shortDescription}
            onChange={(e) => setShortDescription(e.target.value)}
            placeholder={t("shortDescriptionPlaceholder")}
            maxLength={200}
          />
          <p className="text-xs text-muted-foreground mt-1">
            {t("shortDescriptionHelp")}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">
            {t("fullDescription")}{" "}
            <span className="text-destructive">{t("required")}</span>
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
          <label className="block text-sm font-medium mb-2">
            {t("category")}
          </label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full px-3 py-2 rounded-md border bg-background"
          >
            {CATEGORIES.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.label}
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

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-2">
              {t("priceEur")}
            </label>
            <div className="relative">
              <Input
                type="number"
                min="0"
                step="0.01"
                value={priceEur}
                onChange={(e) => setPriceEur(e.target.value)}
                className="pr-8"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                EUR
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {t("freeToActivate")}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">
              {t("creditsPerRun")}
            </label>
            <p className="text-sm text-muted-foreground">
              {t("dynamicCreditsDescription")}
            </p>
          </div>
        </div>

        {/* Images (disabled in publish mode) */}
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-2">{t("images")}</h2>
          <p className="text-sm text-muted-foreground mb-4">
            {t("imagesAfterPublish")}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-6">
            <LogoUpload
              modelId=""
              logoUrl={null}
              onLogoChange={() => {}}
              disabled
            />
            <ScreenshotUpload
              modelId=""
              screenshots={[]}
              onScreenshotsChange={() => {}}
              disabled
            />
          </div>
        </div>

        {/* Model Page Content (sections) */}
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-2">
            {t("modelPageContent")}
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            {t("modelPageContentHelp")}
          </p>
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

        <div className="flex gap-4 pt-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.push("/solve")}
          >
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={publishing} className="flex-1">
            {publishing ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {t("publishing")}
              </>
            ) : (
              <>
                <Upload className="w-4 h-4 mr-2" />
                {t("publishToMarketplace")}
              </>
            )}
          </Button>
        </div>
      </form>

      <dialog.DialogComponent />
    </div>
  );
}

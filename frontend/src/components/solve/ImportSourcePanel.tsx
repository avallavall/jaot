"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { api } from "@/lib/api";
import type {
  Variable,
  Constraint,
  BuilderDocumentListItem,
  TemplateSummary,
  OrganizationModel,
  OptimizationProblem,
} from "@/lib/types";
import type { VariableNodeData, ConstraintNodeData } from "@/lib/builder/types";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { Import, Search, X, FileCode, Box, LayoutTemplate } from "lucide-react";

type TabId = "builder" | "models" | "templates";

interface ImportSourcePanelProps {
  onImport: (variables: Variable[], constraints: Constraint[], sourceName: string) => void;
  importedFrom: string | null;
  onClear: () => void;
}

interface ListItemProps {
  name: string;
  subtitle?: string;
  onImport: () => void;
  loading: boolean;
  t: ReturnType<typeof useTranslations>;
}

function ListItem({ name, subtitle, onImport, loading, t }: ListItemProps) {
  return (
    <div className="flex items-center justify-between p-3 bg-muted/20 border border-border rounded-md hover:bg-muted/40 transition-colors">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{name}</p>
        {subtitle && <p className="text-xs text-muted-foreground truncate">{subtitle}</p>}
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onImport}
        disabled={loading}
        className="ml-3 flex-shrink-0"
      >
        <Import className="h-3.5 w-3.5 mr-1.5" />
        {t("importButton")}
      </Button>
    </div>
  );
}

export function ImportSourcePanel({ onImport, importedFrom, onClear }: ImportSourcePanelProps) {
  const t = useTranslations("solve.multiObjective");
  const { activeWorkspaceId } = useAuth();

  const [activeTab, setActiveTab] = useState<TabId>("builder");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  // Data for each tab
  const [builderDocs, setBuilderDocs] = useState<BuilderDocumentListItem[]>([]);
  const [models, setModels] = useState<OrganizationModel[]>([]);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const loadedTabs = useRef(new Set<TabId>());
  const [tabLoading, setTabLoading] = useState(false);

  // Load data when tab changes
  useEffect(() => {
    if (loadedTabs.current.has(activeTab)) return;

    let cancelled = false;
    setTabLoading(true);

    async function load() {
      try {
        if (activeTab === "builder") {
          const docs = await api.listBuilderDocuments(activeWorkspaceId ?? undefined);
          if (!cancelled) setBuilderDocs(docs);
        } else if (activeTab === "models") {
          const res = await api.getMyModels({ page_size: 100 });
          if (!cancelled) setModels(res.items);
        } else {
          const res = await api.listTemplates();
          if (!cancelled) setTemplates(res.templates);
        }
        if (!cancelled) loadedTabs.current.add(activeTab);
      } catch {
        // Mark as loaded to prevent re-hammering on failure
        if (!cancelled) loadedTabs.current.add(activeTab);
      } finally {
        if (!cancelled) setTabLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [activeTab, activeWorkspaceId]);

  // Filter items by search
  const lowerSearch = search.toLowerCase();

  const filteredBuilderDocs = useMemo(
    () => builderDocs.filter((d) => d.name.toLowerCase().includes(lowerSearch)),
    [builderDocs, lowerSearch],
  );

  const filteredModels = useMemo(
    () => models.filter((m) => (m.display_name || m.custom_name || "").toLowerCase().includes(lowerSearch)),
    [models, lowerSearch],
  );

  const filteredTemplates = useMemo(
    () => templates.filter((t) =>
      t.display_name.toLowerCase().includes(lowerSearch) ||
      t.description.toLowerCase().includes(lowerSearch),
    ),
    [templates, lowerSearch],
  );

  // Import handlers
  async function importFromBuilder(doc: BuilderDocumentListItem) {
    setLoading(true);
    try {
      const full = await api.getBuilderDocument(doc.id, activeWorkspaceId ?? undefined);

      // Try model_json first (compiled model)
      const modelJson = full.model_json as OptimizationProblem | null;
      if (modelJson?.variables && modelJson.variables.length > 0) {
        onImport(modelJson.variables, modelJson.constraints ?? [], doc.name);
        toast.success(t("importSuccess", { name: doc.name }));
        return;
      }

      // Fall back to parsing canvas_json nodes
      const canvas = full.canvas_json as {
        nodes?: Array<{ type: string; data: VariableNodeData | ConstraintNodeData }>;
      } | null;
      if (!canvas?.nodes) {
        toast.error(t("importFailed"));
        return;
      }

      const variables: Variable[] = canvas.nodes
        .filter((n) => n.type === "variable")
        .map((n) => {
          const d = n.data as VariableNodeData;
          return {
            name: d.name || "x",
            type: d.type || "continuous",
            ...(d.lower_bound != null && { lower_bound: Number(d.lower_bound) }),
            ...(d.upper_bound != null && { upper_bound: Number(d.upper_bound) }),
          };
        });

      const constraints: Constraint[] = canvas.nodes
        .filter((n) => n.type === "constraint")
        .flatMap((n) => {
          const d = n.data as ConstraintNodeData;
          if (!d.formula) return [];
          return [{ expression: d.formula }];
        });

      if (variables.length === 0) {
        toast.error(t("importFailed"));
        return;
      }

      onImport(variables, constraints, doc.name);
      toast.success(t("importSuccess", { name: doc.name }));
    } catch {
      toast.error(t("importFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function importFromModel(model: OrganizationModel) {
    setLoading(true);
    try {
      const schema = await api.getMyModelSchema(model.id);
      const inputData = schema.example_input ?? {};
      if (Object.keys(inputData).length > 0) {
        toast.info(t("needsInputData"));
      }
      const problem = await api.previewModel(model.id, inputData);
      const name = model.display_name || model.custom_name || model.id;
      onImport(problem.variables, problem.constraints ?? [], name);
      toast.success(t("importSuccess", { name }));
    } catch {
      toast.error(t("importFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function importFromTemplate(tmpl: TemplateSummary) {
    setLoading(true);
    try {
      const problem = await api.previewTemplate(tmpl.id);
      onImport(problem.variables, problem.constraints ?? [], tmpl.display_name);
      toast.success(t("importSuccess", { name: tmpl.display_name }));
    } catch {
      toast.error(t("importFailed"));
    } finally {
      setLoading(false);
    }
  }

  // If already imported, show compact banner
  if (importedFrom) {
    return (
      <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Import className="h-4 w-4 text-primary" />
            <span className="font-medium">{t("importedFrom", { name: importedFrom })}</span>
          </div>
          <Button variant="ghost" size="sm" onClick={onClear} className="text-muted-foreground">
            <X className="h-3.5 w-3.5 mr-1" />
            {t("clearImport")}
          </Button>
        </div>
      </div>
    );
  }

  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "builder", label: t("tabBuilder"), icon: <FileCode className="h-4 w-4" /> },
    { id: "models", label: t("tabMyModels"), icon: <Box className="h-4 w-4" /> },
    { id: "templates", label: t("tabTemplates"), icon: <LayoutTemplate className="h-4 w-4" /> },
  ];

  return (
    <div className="bg-card border border-border rounded-lg p-6 mb-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Import className="h-5 w-5 text-primary" />
          {t("importSource")}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">{t("importSourceDescription")}</p>
      </div>

      <div className="flex gap-1 mb-4 border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("searchPlaceholder")}
          className="w-full pl-9 pr-3 py-2 text-sm bg-background border border-border rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
          data-testid="import-search"
        />
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto" data-testid="import-list">
        {tabLoading && (
          <p className="text-sm text-muted-foreground text-center py-4">{t("loadingItems")}</p>
        )}

        {!tabLoading && activeTab === "builder" && (
          <>
            {filteredBuilderDocs.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">{t("noBuilderDocs")}</p>
            )}
            {filteredBuilderDocs.map((doc) => (
              <ListItem
                key={doc.id}
                name={doc.name}
                subtitle={new Date(doc.updated_at).toLocaleDateString()}
                onImport={() => importFromBuilder(doc)}
                loading={loading}
                t={t}
              />
            ))}
          </>
        )}

        {!tabLoading && activeTab === "models" && (
          <>
            {filteredModels.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">{t("noModels")}</p>
            )}
            {filteredModels.map((model) => (
              <ListItem
                key={model.id}
                name={model.display_name || model.custom_name || model.id}
                subtitle={model.catalog_id ? `Catalog: ${model.catalog_id}` : "Private model"}
                onImport={() => importFromModel(model)}
                loading={loading}
                t={t}
              />
            ))}
          </>
        )}

        {!tabLoading && activeTab === "templates" && (
          <>
            {filteredTemplates.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">{t("noTemplates")}</p>
            )}
            {filteredTemplates.map((tmpl) => (
              <ListItem
                key={tmpl.id}
                name={tmpl.display_name}
                subtitle={tmpl.description}
                onImport={() => importFromTemplate(tmpl)}
                loading={loading}
                t={t}
              />
            ))}
          </>
        )}
      </div>

      <p className="text-xs text-muted-foreground mt-4 text-center">
        {t("orDefineFromScratch")}
      </p>
    </div>
  );
}

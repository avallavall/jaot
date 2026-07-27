"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { RegistryEntry, SettingValue } from "@/lib/api";
import type { AdminStats } from "@/lib/types";
import { useTranslations } from "next-intl";

import { SystemTab } from "@/components/admin/settings/SystemTab";
import type { HealthData } from "@/components/admin/settings/SystemTab";
import { SettingsTab } from "@/components/admin/settings/SettingsTab";
import { SecretsTab } from "@/components/admin/settings/SecretsTab";
import { AuditLogTab } from "@/components/admin/settings/AuditLogTab";

/**
 * Tabs group backend categories by what an operator came to do, not by which
 * table the value lives in.
 *
 * `secrets` is deliberately absent: it has its own tab with a different editor.
 * Any other category the backend adds and this list does not name falls into
 * `advanced` (see ADVANCED_TAB) rather than vanishing — before that fallback
 * existed, six categories including all of RAG had no tab at all and could
 * only be changed with SQL.
 */
const TAB_GROUPS = [
  { key: "instance", categories: ["system", "app"] },
  { key: "access", categories: ["security", "limits"] },
  { key: "ai", categories: ["llm", "rag"] },
  { key: "solver", categories: ["solver"] },
  { key: "email", categories: ["email"] },
] as const;

/** Catch-all for low-level categories: named ones plus anything unmapped. */
const ADVANCED_CATEGORIES = ["identifiers"];

/** Handled by dedicated tabs, never folded into `advanced`. */
const NON_SETTING_CATEGORIES = new Set(["secrets"]);

export default function SettingsPage() {
  const t = useTranslations("admin.settings");
  const [health, setHealth] = useState<HealthData | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  const [allEntries, setAllEntries] = useState<RegistryEntry[]>([]);
  const [allValues, setAllValues] = useState<Record<string, SettingValue>>({});
  const [categories, setCategories] = useState<string[]>([]);

  const fetchSettingsData = useCallback(async () => {
    try {
      const [registryData, valuesData] = await Promise.all([
        api.admin.getSettingsRegistry(),
        api.admin.getSettingsValues(),
      ]);

      // Flatten all entries from all categories
      const entries: RegistryEntry[] = [];
      const cats: string[] = [];
      for (const [cat, catEntries] of Object.entries(registryData.categories)) {
        cats.push(cat);
        entries.push(...catEntries);
      }
      setAllEntries(entries);
      setCategories(cats);
      setAllValues(valuesData.settings);
    } catch (err) {
      console.warn('Failed to load settings data:', err);
    }
  }, []);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [healthData, statsData] = await Promise.all([
          api.request<HealthData>("/api/v2/health"),
          api.admin.getStats(),
        ]);
        setHealth(healthData);
        setStats(statsData);
      } catch (err) {
        console.warn('Failed to load health data:', err);
      } finally {
        setLoading(false);
      }
    };
    loadData();
    fetchSettingsData();
  }, [fetchSettingsData]);

  const isSearching = searchQuery.trim().length > 0;

  /**
   * Advanced absorbs its own categories plus every category the backend sent
   * that no tab claims — the guarantee that a new backend category is always
   * reachable somewhere.
   */
  const advancedCategories = useMemo(() => {
    const claimed = new Set<string>([
      ...TAB_GROUPS.flatMap((tab) => tab.categories as readonly string[]),
      ...ADVANCED_CATEGORIES,
    ]);
    const unmapped = categories.filter(
      (c) => !claimed.has(c) && !NON_SETTING_CATEGORIES.has(c)
    );
    return [...ADVANCED_CATEGORIES, ...unmapped];
  }, [categories]);

  /** Every tab that renders editable settings, in display order. */
  const settingTabs = useMemo(
    () => [
      ...TAB_GROUPS.map((tab) => ({
        key: tab.key as string,
        categories: tab.categories as readonly string[],
      })),
      { key: "advanced", categories: advancedCategories as readonly string[] },
    ],
    [advancedCategories]
  );

  // Which tabs have a setting matching the query. Searches every tab that
  // holds settings — the previous version skipped System entirely, so half
  // the panel was unsearchable.
  const searchMatchTabs = useMemo(() => {
    if (!isSearching) return [];
    const q = searchQuery.toLowerCase();
    const matched = new Set<string>();
    for (const entry of allEntries) {
      if (entry.is_secret) continue;
      if (
        entry.label.toLowerCase().includes(q) ||
        entry.description.toLowerCase().includes(q) ||
        entry.key.toLowerCase().includes(q)
      ) {
        matched.add(entry.category);
      }
    }
    return settingTabs.filter((tab) =>
      tab.categories.some((c) => matched.has(c))
    );
  }, [isSearching, searchQuery, allEntries, settingTabs]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">{t("subtitle")}</p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t("searchPlaceholder")}
          className="pl-9 pr-9"
        />
        {isSearching && (
          <button
            onClick={() => setSearchQuery("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {allEntries.length === 0 && !loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : isSearching ? (
        /* Search results: matching tabs, flattened, each labelled with its tab */
        <div className="space-y-4">
          {searchMatchTabs.length === 0 ? (
            <p className="text-muted-foreground text-sm py-8 text-center">
              {t("searchNoResults")}
            </p>
          ) : (
            searchMatchTabs.map((tab) => (
              <div key={tab.key} className="relative">
                <Badge
                  variant="secondary"
                  className="absolute -top-2 left-4 z-10"
                >
                  {t(`tabs.${tab.key}`)}
                </Badge>
                <SettingsTab
                  categories={tab.categories}
                  categoryLabel={t(`tabs.${tab.key}`)}
                  entries={allEntries}
                  values={allValues}
                  onRefresh={fetchSettingsData}
                  searchQuery={searchQuery}
                />
              </div>
            ))
          )}
        </div>
      ) : (
        <Tabs defaultValue="instance" className="space-y-4">
          <TabsList className="flex flex-wrap h-auto gap-1">
            {settingTabs.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key}>
                {t(`tabs.${tab.key}`)}
              </TabsTrigger>
            ))}
            <TabsTrigger value="secrets">{t("tabs.secrets")}</TabsTrigger>
            <TabsTrigger value="auditLog">{t("tabs.auditLog")}</TabsTrigger>
          </TabsList>

          <TabsContent value="instance" className="space-y-6">
            <SystemTab health={health} stats={stats} loading={loading} />
            <SettingsTab
              categories={["system", "app"]}
              categoryLabel={t("tabs.instance")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="access" className="space-y-6">
            <SettingsTab
              categories={["security"]}
              categoryLabel={t("tabs.access")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
            <SettingsTab
              categories={["limits"]}
              categoryLabel={t("tabs.limits")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="ai">
            <SettingsTab
              categories={["llm", "rag"]}
              categoryLabel={t("tabs.ai")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="solver">
            <SettingsTab
              categories={["solver"]}
              categoryLabel={t("tabs.solver")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="email">
            <SettingsTab
              categories={["email"]}
              categoryLabel={t("tabs.email")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="advanced">
            <SettingsTab
              categories={advancedCategories}
              categoryLabel={t("tabs.advanced")}
              warning={t("advancedWarning")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="secrets">
            <SecretsTab entries={allEntries} values={allValues} />
          </TabsContent>

          <TabsContent value="auditLog">
            <AuditLogTab categories={categories} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

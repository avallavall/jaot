"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type {
  RegistryEntry,
  SettingValue,
  PlanTiersResponse,
} from "@/lib/api";
import type { AdminStats } from "@/lib/types";
import { useTranslations } from "next-intl";

import { SystemTab } from "@/components/admin/settings/SystemTab";
import type { HealthData } from "@/components/admin/settings/SystemTab";
import { SettingsTab } from "@/components/admin/settings/SettingsTab";
import { PlanTierTable } from "@/components/admin/settings/PlanTierTable";
import { SecretsTab } from "@/components/admin/settings/SecretsTab";
import { AuditLogTab } from "@/components/admin/settings/AuditLogTab";

const SETTING_TABS = [
  { key: "system", category: null },
  { key: "billing", category: "billing" },
  { key: "solver", category: "solver" },
  { key: "llm", category: "llm" },
  { key: "email", category: "email" },
  { key: "security", category: "security" },
  { key: "marketplace", category: "marketplace" },
  { key: "secrets", category: null },
  { key: "auditLog", category: null },
] as const;

/** Tabs that have a SettingsTab with searchable entries */
const SEARCHABLE_TABS = SETTING_TABS.filter(
  (tab): tab is (typeof SETTING_TABS)[number] & { category: string } =>
    tab.category !== null
);

export default function SettingsPage() {
  const t = useTranslations("admin.settings");
  const [health, setHealth] = useState<HealthData | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  const [allEntries, setAllEntries] = useState<RegistryEntry[]>([]);
  const [allValues, setAllValues] = useState<Record<string, SettingValue>>({});
  const [categories, setCategories] = useState<string[]>([]);
  const [planTiers, setPlanTiers] = useState<PlanTiersResponse | null>(null);

  const fetchSettingsData = useCallback(async () => {
    try {
      const [registryData, valuesData, planData] = await Promise.all([
        api.admin.getSettingsRegistry(),
        api.admin.getSettingsValues(),
        api.admin.getPlanTiers(),
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
      setPlanTiers(planData);
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

  // Find which categories have matching results during search
  const searchMatchCategories = useMemo(() => {
    if (!isSearching) return [];
    const q = searchQuery.toLowerCase();
    const matched = new Set<string>();
    for (const entry of allEntries) {
      if (entry.is_secret) continue;
      if (
        entry.label.toLowerCase().includes(q) ||
        entry.description.toLowerCase().includes(q)
      ) {
        matched.add(entry.category);
      }
    }
    return SEARCHABLE_TABS.filter((tab) => tab.category && matched.has(tab.category));
  }, [isSearching, searchQuery, allEntries]);

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
        /* Search results: flat list of matching SettingsTabs with category badges */
        <div className="space-y-4">
          {searchMatchCategories.length === 0 ? (
            <p className="text-muted-foreground text-sm py-8 text-center">
              {t("searchNoResults")}
            </p>
          ) : (
            searchMatchCategories.map((tab) => (
              <div key={tab.key} className="relative">
                <Badge
                  variant="secondary"
                  className="absolute -top-2 left-4 z-10"
                >
                  {t(`tabs.${tab.key}`)}
                </Badge>
                <SettingsTab
                  category={tab.category!}
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
        <Tabs defaultValue="system" className="space-y-4">
          <TabsList className="flex flex-wrap h-auto gap-1">
            {SETTING_TABS.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key}>
                {t(`tabs.${tab.key}`)}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="system" className="space-y-6">
            <SystemTab health={health} stats={stats} loading={loading} />
            <SettingsTab
              category="system"
              categoryLabel={t("tabs.systemSettings")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          {/* Billing Tab - Plan Tier Table + billing settings */}
          <TabsContent value="billing" className="space-y-6">
            <PlanTierTable data={planTiers} onRefresh={fetchSettingsData} />
            <SettingsTab
              category="billing"
              categoryLabel={t("tabs.billing")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="solver">
            <SettingsTab
              category="solver"
              categoryLabel={t("tabs.solver")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="llm">
            <SettingsTab
              category="llm"
              categoryLabel={t("tabs.llm")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="email">
            <SettingsTab
              category="email"
              categoryLabel={t("tabs.email")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="security">
            <SettingsTab
              category="security"
              categoryLabel={t("tabs.security")}
              entries={allEntries}
              values={allValues}
              onRefresh={fetchSettingsData}
            />
          </TabsContent>

          <TabsContent value="marketplace">
            <SettingsTab
              category="marketplace"
              categoryLabel={t("tabs.marketplace")}
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

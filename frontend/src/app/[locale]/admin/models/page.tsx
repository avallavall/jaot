"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import type { PaginatedResponse } from "@/lib/types";

interface AdminModel {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  category?: string;
  version: string;
  is_official: boolean;
  is_featured: boolean;
  is_public: boolean;
  credits_per_execution: number;
  created_at: string;
}

export default function ModelsPage() {
  const t = useTranslations("admin.models");
  const tc = useTranslations("common");
  const { categoryLabel } = useCommonLabels();
  const [models, setModels] = useState<AdminModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [publicFilter, setPublicFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [categories, setCategories] = useState<string[]>([]);

  useEffect(() => {
    loadModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, categoryFilter, publicFilter]);

  const loadModels = async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(page) };
      if (categoryFilter) params.category = categoryFilter;
      if (publicFilter) params.is_public = publicFilter;

      const query = new URLSearchParams(params).toString();
      const data = await api.request<PaginatedResponse<AdminModel>>(`/api/v2/admin/models?${query}`);
      setModels(data.items);
      setTotalPages(data.total_pages ?? 1);

      // Extract unique categories
      const cats = [...new Set(data.items.map((s: AdminModel) => s.category).filter(Boolean))] as string[];
      if (cats.length > categories.length) {
        setCategories(cats);
      }
    } catch (err) {
      console.warn('Failed to load models:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggleVisibility = async (modelId: string, currentPublic: boolean) => {
    try {
      await api.request(`/api/v2/admin/models/${modelId}/visibility?is_public=${!currentPublic}`, { method: 'PATCH' });
      loadModels();
    } catch {
      // Failed to toggle visibility
    }
  };

  const handleToggleBadge = async (modelId: string, badge: 'is_official' | 'is_featured', currentValue: boolean) => {
    try {
      await api.request(`/api/v2/admin/models/${modelId}`, {
        method: 'PATCH',
        body: JSON.stringify({ [badge]: !currentValue })
      });
      loadModels();
    } catch {
      // Failed to toggle badge
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">
          {t("subtitle")}
        </p>
      </div>

      <Card className="border-border">
        <CardContent className="pt-4">
          <div className="flex gap-4">
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="p-2 border border-input bg-background text-sm"
            >
              <option value="">{t("allCategories")}</option>
              {categories.map(cat => (
                <option key={cat} value={cat}>{categoryLabel(cat)}</option>
              ))}
            </select>
            <select
              value={publicFilter}
              onChange={(e) => setPublicFilter(e.target.value)}
              className="p-2 border border-input bg-background text-sm"
            >
              <option value="">{t("allTypes")}</option>
              <option value="true">{t("public")}</option>
              <option value="false">{t("private")}</option>
            </select>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <Table className="table-fixed w-full">
            <TableHeader>
              <TableRow className="border-border">
                <TableHead className="w-[30%]">{t("tableHeaders.model")}</TableHead>
                <TableHead className="w-[12%]">{t("tableHeaders.category")}</TableHead>
                <TableHead className="w-[13%]">{t("tableHeaders.badges")}</TableHead>
                <TableHead className="w-[8%]">{t("tableHeaders.version")}</TableHead>
                <TableHead className="w-[10%]">{t("tableHeaders.cost")}</TableHead>
                <TableHead className="w-[12%]">{t("tableHeaders.visibility")}</TableHead>
                <TableHead className="w-[15%]">{t("tableHeaders.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : models.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {t("noModels")}
                  </TableCell>
                </TableRow>
              ) : (
                models.map((model) => (
                  <TableRow key={model.id} className="border-border">
                    <TableCell className="max-w-0">
                      <div className="min-w-0">
                        <span className="font-medium truncate block">
                          {model.display_name || model.name}
                        </span>
                        {model.description && (
                          <p className="text-xs text-muted-foreground line-clamp-1 truncate">
                            {model.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-0">
                      {model.category ? (
                        <Badge variant="outline" className="truncate max-w-full">{categoryLabel(model.category)}</Badge>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        <button
                          onClick={() => handleToggleBadge(model.id, 'is_official', model.is_official)}
                          className={`px-2 py-0.5 text-xs rounded cursor-pointer transition-colors ${
                            model.is_official
                              ? 'bg-blue-100 text-blue-800 hover:bg-blue-200'
                              : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                          }`}
                        >
                          {t("official")}
                        </button>
                        <button
                          onClick={() => handleToggleBadge(model.id, 'is_featured', model.is_featured)}
                          className={`px-2 py-0.5 text-xs rounded cursor-pointer transition-colors ${
                            model.is_featured
                              ? 'bg-yellow-100 text-yellow-800 hover:bg-yellow-200'
                              : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                          }`}
                        >
                          {t("featured")}
                        </button>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      v{model.version}
                    </TableCell>
                    <TableCell>
                      <span>{t("costUnit", { amount: model.credits_per_execution })}</span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={model.is_public ? "default" : "secondary"}>
                        {model.is_public ? t("public") : t("private")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleToggleVisibility(model.id, model.is_public)}
                      >
                        {model.is_public ? t("makePrivate") : t("makePublic")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          </div>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            {tc("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageOf", { page, totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            {tc("next")}
          </Button>
        </div>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";

export default function NewWorkspacePage() {
  const router = useRouter();
  const { isOwner, isLoading } = useAuth();
  const t = useTranslations("workspace.newWorkspace");
  const tc = useTranslations("common");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  // Redirect non-owners after auth loads
  useEffect(() => {
    if (!isLoading && !isOwner) {
      toast.error(t("ownerRequired"));
      router.replace("/workspace/workspaces");
    }
  }, [isLoading, isOwner, router, t]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const ws = await api.createWorkspace({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      toast.success(`Workspace "${ws.name}" created`);
      router.push(`/workspace/workspaces/${ws.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("createError"));
    } finally {
      setCreating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-lg">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-1/2 bg-muted rounded" />
          <div className="h-10 bg-muted rounded" />
          <div className="h-20 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (!isOwner) return null;

  return (
    <div className="container mx-auto px-4 py-8 max-w-lg">
      <div className="mb-6">
        <Button variant="ghost" size="sm" asChild className="mb-4 -ml-2">
          <Link href="/workspace/workspaces">
            <ArrowLeft className="w-4 h-4 mr-1" />
            {t("backToWorkspaces")}
          </Link>
        </Button>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground mt-1">
          {t("subtitle")}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">
            {t("nameLabel")} <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            placeholder={t("namePlaceholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoFocus
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">{t("descriptionLabel")}</Label>
          <Textarea
            id="description"
            placeholder={t("descriptionPlaceholder")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>

        <div className="flex gap-3 pt-2">
          <Button type="submit" disabled={!name.trim() || creating}>
            {creating ? t("creating") : t("createButton")}
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link href="/workspace/workspaces">{tc("cancel")}</Link>
          </Button>
        </div>
      </form>
    </div>
  );
}

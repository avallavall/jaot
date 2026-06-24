"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useDialog } from "@/components/ui/dialog-custom";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Key, Plus, Copy, Eye, EyeOff, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/guidance/EmptyState";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { APIKey as APIKeyInfo } from "@/lib/types";

export default function ClientAPIKeysPage() {
  const t = useTranslations("workspace.apiKeys");
  const tc = useTranslations("common");
  const dialog = useDialog();
  const [keys, setKeys] = useState<APIKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    setLoading(true);
    try {
      const data = await api.getKeys();
      setKeys(data || []);
    } catch {
      // Failed to load API keys
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;

    try {
      const data = await api.createKey({ name: newKeyName });
      setNewKeyValue(data.api_key);
      setShowKey(true);
      loadKeys();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("createError")));
    }
  };

  const handleCopyKey = () => {
    if (newKeyValue) {
      navigator.clipboard.writeText(newKeyValue);
      dialog.showSuccess(t("copied"), t("copiedMessage"));
    }
  };

  const handleCloseNewKey = () => {
    setIsCreateOpen(false);
    setNewKeyName("");
    setNewKeyValue(null);
    setShowKey(false);
  };

  const handleDelete = async (keyId: string) => {
    const confirmed = await dialog.confirm(
      t("deleteConfirm"),
      t("deleteTitle")
    );
    if (!confirmed) return;

    try {
      await api.deleteKey(keyId);
      dialog.showSuccess(t("deleted"), t("deletedMessage"));
      loadKeys();
    } catch (err) {
      dialog.showError(getErrorMessage(err, t("deleteError")));
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return t("never");
    return new Date(dateStr).toLocaleDateString();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
          <p className="text-muted-foreground mt-1">
            {t("subtitle")}
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)}>
          <Plus className="w-4 h-4 mr-2" />
          {t("createKey")}
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" aria-busy="true"></div>
        </div>
      ) : keys.length === 0 ? (
        <EmptyState
          icon={<Key className="h-12 w-12" />}
          title={t("noKeysTitle")}
          description={t("noKeysDescription")}
          expertDescription={t("noKeysExpert")}
          actionLabel={t("createFirstKey")}
          onAction={() => setIsCreateOpen(true)}
        />
      ) : (
        <Card className="border-border">
          <CardHeader>
            <CardTitle className="text-lg font-serif flex items-center gap-2">
              <Key className="w-5 h-5" />
              {t("yourApiKeys")}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="border-border">
                  <TableHead>{t("tableHeaders.name")}</TableHead>
                  <TableHead>{t("tableHeaders.key")}</TableHead>
                  <TableHead>{t("tableHeaders.status")}</TableHead>
                  <TableHead>{t("tableHeaders.created")}</TableHead>
                  <TableHead>{t("tableHeaders.lastUsed")}</TableHead>
                  <TableHead>{t("tableHeaders.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((key) => (
                  <TableRow key={key.id} className="border-border">
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground">
                      {key.key_prefix}...
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={key.is_active ? "default" : "secondary"}
                      >
                        {key.is_active ? t("active") : t("inactive")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(key.created_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(key.last_used_at ?? null)}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => handleDelete(key.id)}
                        aria-label={t("deleteAriaLabel", { name: key.name })}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Dialog open={isCreateOpen} onOpenChange={handleCloseNewKey}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="font-serif">
              {newKeyValue ? t("apiKeyCreated") : t("createApiKey")}
            </DialogTitle>
          </DialogHeader>

          {newKeyValue ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t("copyWarning")}
              </p>
              <div className="flex items-center gap-2">
                <Input
                  type={showKey ? "text" : "password"}
                  value={newKeyValue}
                  readOnly
                  className="font-mono text-sm"
                />
                <Button variant="outline" size="icon" onClick={() => setShowKey(!showKey)} aria-label={showKey ? t("hideKey") : t("showKey")}>
                  {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </Button>
                <Button variant="outline" size="icon" onClick={handleCopyKey} aria-label={t("copyKey")}>
                  <Copy className="w-4 h-4" />
                </Button>
              </div>
              <Button onClick={handleCloseNewKey} className="w-full">
                {t("done")}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label htmlFor="api-key-name" className="block text-sm font-medium mb-1">{t("keyName")}</label>
                <Input
                  id="api-key-name"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder={t("keyPlaceholder")}
                />
              </div>
              <div className="flex gap-2">
                <Button onClick={handleCreate} className="flex-1">
                  {t("createKey")}
                </Button>
                <Button variant="outline" onClick={handleCloseNewKey}>
                  {tc("cancel")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <dialog.DialogComponent />
    </div>
  );
}

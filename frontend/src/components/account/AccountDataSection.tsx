"use client";

import { useState } from "react";
import { Download, Trash2, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDialog } from "@/components/ui/dialog-custom";

/**
 * Personal account data controls: export (GDPR data export) and permanent
 * account deletion. Lives on "My Profile" so these per-user actions are always
 * reachable from the sidebar, independent of whether the user has a workspace.
 */
export function AccountDataSection() {
  const t = useTranslations("workspace.accountData");
  const tc = useTranslations("common");
  const tError = useTranslations("errors.codes");
  const dialog = useDialog();

  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [showDeleteSection, setShowDeleteSection] = useState(false);
  // Shown under the password field. The refusal went to a dialog this section
  // never rendered, so a wrong password showed nothing at all.
  const [deleteError, setDeleteError] = useState("");

  const handleExport = async () => {
    setExporting(true);
    try {
      await api.exportUserData();
      dialog.showSuccess(t("exportSuccess"));
    } catch {
      dialog.showError(t("exportError"));
    } finally {
      setExporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    setDeleteError("");
    try {
      await api.deleteUserAccount(deletePassword);
      // A full page load, not a client navigation: the account is gone, and
      // nothing the app holds in memory about it may survive.
      window.location.assign(new URL("/", window.location.origin).href);
    } catch (err) {
      setDeleteError(translateApiError(err, tError, t("deleteError")));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="bg-card border rounded-lg p-6 mt-6">
      <h3 className="text-lg font-semibold mb-2">{t("account")}</h3>
      <p className="text-sm text-muted-foreground mb-4">
        {t("accountDescription")}
      </p>

      <div className="space-y-4">
        <div className="p-4 border rounded-lg">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="font-medium flex items-center gap-2">
                <Download className="w-4 h-4" />
                {t("exportData")}
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                {t("exportDescription")}
              </p>
            </div>
            <Button
              variant="outline"
              disabled={exporting}
              onClick={handleExport}
            >
              {exporting ? t("exporting") : t("exportButton")}
            </Button>
          </div>
        </div>

        <div className="p-4 border border-destructive/30 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-destructive" />
            <span className="font-medium text-destructive">
              {t("deleteAccount")}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            {t("deleteWarning")}
          </p>
          {!showDeleteSection ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowDeleteSection(true)}
            >
              <Trash2 className="w-4 h-4 mr-2" /> {t("deleteButton")}
            </Button>
          ) : (
            <div className="space-y-3 p-4 bg-destructive/5 rounded-md">
              <p className="text-sm font-medium">{t("deleteConfirmPrompt")}</p>
              <Input
                placeholder={t("deleteTypePlaceholder")}
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
              />
              <Input
                type="password"
                placeholder={t("deletePasswordPlaceholder")}
                aria-label={t("deletePasswordPlaceholder")}
                value={deletePassword}
                aria-invalid={deleteError ? true : undefined}
                onChange={(e) => {
                  setDeletePassword(e.target.value);
                  setDeleteError("");
                }}
              />
              {deleteError && (
                <p role="alert" className="text-sm text-destructive">
                  {deleteError}
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  variant="destructive"
                  disabled={
                    deleteConfirm !== "DELETE" || !deletePassword || deleting
                  }
                  onClick={handleDeleteAccount}
                >
                  {deleting ? t("deleting") : t("permanentlyDelete")}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteSection(false);
                    setDeleteConfirm("");
                    setDeletePassword("");
                    setDeleteError("");
                  }}
                >
                  {tc("cancel")}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
      {/* The export's success and failure messages go through this dialog. It
          was never rendered, so neither message ever showed. */}
      <dialog.DialogComponent />
    </div>
  );
}

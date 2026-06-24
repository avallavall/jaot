"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useDialog } from "@/components/ui/dialog-custom";
import { useAuth } from "@/contexts/AuthContext";
import {
  Building2,
  Globe,
  Linkedin,
  Twitter,
  Save,
  Eye,
  CheckCircle,
  Download,
  Trash2,
  AlertTriangle,
} from "lucide-react";
import { useTranslations } from "next-intl";
import type { OrgProfile } from "@/lib/types";

type OrganizationPublicProfile = OrgProfile & { is_public_profile?: boolean };

export default function OrganizationProfileSettingsPage() {
  const dialog = useDialog();
  const { organization } = useAuth();
  const t = useTranslations("workspace.orgProfile");
  const tc = useTranslations("common");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [profile, setProfile] = useState<OrganizationPublicProfile | null>(null);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [showDeleteSection, setShowDeleteSection] = useState(false);

  // Form fields
  const [slug, setSlug] = useState("");
  const [bio, setBio] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [twitterUrl, setTwitterUrl] = useState("");
  const [isPublic, setIsPublic] = useState(false);

  useEffect(() => {
    if (organization) {
      loadProfile();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organization]);

  const loadProfile = async () => {
    if (!organization) return;
    setLoading(true);
    try {
      const data = await api.getOrgProfile(organization.id) as unknown as OrganizationPublicProfile;
      setProfile(data);
      setSlug(data.slug || "");
      setBio(data.bio || "");
      setLogoUrl(data.logo_url || "");
      setWebsiteUrl(data.website_url || "");
      setLinkedinUrl(data.linkedin_url || "");
      setTwitterUrl(data.twitter_url || "");
      setIsPublic(data.is_public_profile || false);
    } catch {
      dialog.showError(t("loadError"));
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateOrgProfile({
        slug: slug || null,
        bio: bio || null,
        logo_url: logoUrl || null,
        website_url: websiteUrl || null,
        linkedin_url: linkedinUrl || null,
        twitter_url: twitterUrl || null,
        is_public_profile: isPublic,
      });
      dialog.showSuccess(t("profileUpdated"));
      loadProfile();
    } catch (err) {
      dialog.showError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

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
    try {
      await api.deleteUserAccount(deletePassword);
      // Redirect to homepage after deletion
      window.location.href = "/";
    } catch (err) {
      dialog.showError(err instanceof Error ? err.message : t("deleteError"));
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12" aria-busy="true">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        <span className="sr-only">{t("loadingProfile")}</span>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2">{t("title")}</h1>
        <p className="text-muted-foreground">
          {t("subtitle")}
        </p>
      </div>

      {profile && (
        <div className={`mb-6 p-4 rounded-lg border ${
          profile.is_verified
            ? "bg-green-50 border-green-200"
            : "bg-muted border-border"
        }`}>
          <div className="flex items-center gap-2">
            {profile.is_verified ? (
              <>
                <CheckCircle className="w-5 h-5 text-green-600" />
                <span className="font-medium text-green-800">{t("verifiedPublisher")}</span>
              </>
            ) : (
              <>
                <Building2 className="w-5 h-5 text-muted-foreground" />
                <span className="text-muted-foreground">{t("notVerified")}</span>
              </>
            )}
          </div>
          {!profile.is_verified && (
            <p className="text-sm text-muted-foreground mt-2">
              {t("verificationHint")}
            </p>
          )}
        </div>
      )}

      <div className="space-y-6">
        <div>
          <label htmlFor="profile-url" className="block text-sm font-medium mb-2">
            {t("profileUrl")}
          </label>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground text-sm">/org/</span>
            <Input
              id="profile-url"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
              placeholder="your-company"
              className="flex-1"
            />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {t("urlHint")}
          </p>
        </div>

        <div>
          <label htmlFor="profile-bio" className="block text-sm font-medium mb-2">
            {t("bio")}
          </label>
          <Textarea
            id="profile-bio"
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder={t("bioPlaceholder")}
            className="min-h-[100px]"
            maxLength={1000}
          />
          <p className="text-xs text-muted-foreground mt-1">
            {t("bioCount", { count: bio.length })}
          </p>
        </div>

        <div>
          <label htmlFor="profile-logo-url" className="block text-sm font-medium mb-2">
            {t("logoUrl")}
          </label>
          <Input
            id="profile-logo-url"
            value={logoUrl}
            onChange={(e) => setLogoUrl(e.target.value)}
            placeholder={t("logoPlaceholder")}
          />
        </div>

        <div>
          <label htmlFor="profile-website" className="block text-sm font-medium mb-2 flex items-center gap-2">
            <Globe className="w-4 h-4" />
            {t("website")}
          </label>
          <Input
            id="profile-website"
            value={websiteUrl}
            onChange={(e) => setWebsiteUrl(e.target.value)}
            placeholder={t("websitePlaceholder")}
          />
        </div>

        <div>
          <label htmlFor="profile-linkedin" className="block text-sm font-medium mb-2 flex items-center gap-2">
            <Linkedin className="w-4 h-4" />
            {t("linkedin")}
          </label>
          <Input
            id="profile-linkedin"
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
            placeholder={t("linkedinPlaceholder")}
          />
        </div>

        <div>
          <label htmlFor="profile-twitter" className="block text-sm font-medium mb-2 flex items-center gap-2">
            <Twitter className="w-4 h-4" />
            {t("twitter")}
          </label>
          <Input
            id="profile-twitter"
            value={twitterUrl}
            onChange={(e) => setTwitterUrl(e.target.value)}
            placeholder={t("twitterPlaceholder")}
          />
        </div>

        <div className="flex items-center justify-between p-4 border rounded-lg">
          <div className="flex items-center gap-3">
            <Eye className="w-5 h-5 text-muted-foreground" />
            <div>
              <div className="font-medium">{t("publicProfile")}</div>
              <div className="text-sm text-muted-foreground">
                {t("publicProfileDescription")}
              </div>
            </div>
          </div>
          <label htmlFor="profile-public-toggle" className="relative inline-flex items-center cursor-pointer">
            <input
              id="profile-public-toggle"
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
          </label>
        </div>

        <div className="pt-4">
          <Button onClick={handleSave} disabled={saving} className="w-full">
            {saving ? (
              t("saving")
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                {t("saveChanges")}
              </>
            )}
          </Button>
        </div>

        {slug && (
          <div className="text-center">
            <a
              href={`/org/${slug}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-primary hover:underline"
            >
              {t("previewProfile")} &rarr;
            </a>
          </div>
        )}
      </div>

      <div className="border-t my-10" />

      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold mb-2">{t("account")}</h2>
          <p className="text-muted-foreground text-sm">{t("accountDescription")}</p>
        </div>

        <div className="p-4 border rounded-lg">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium flex items-center gap-2">
                <Download className="w-4 h-4" />
                {t("exportData")}
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                {t("exportDescription")}
              </p>
            </div>
            <Button variant="outline" disabled={exporting} onClick={handleExport}>
              {exporting ? t("exporting") : t("exportButton")}
            </Button>
          </div>
        </div>

        <div className="p-4 border border-destructive/30 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-destructive" />
            <span className="font-medium text-destructive">{t("deleteAccount")}</span>
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            {t("deleteWarning")}
          </p>
          {!showDeleteSection ? (
            <Button variant="destructive" size="sm" onClick={() => setShowDeleteSection(true)}>
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
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
              />
              <div className="flex gap-2">
                <Button
                  variant="destructive"
                  disabled={deleteConfirm !== "DELETE" || !deletePassword || deleting}
                  onClick={handleDeleteAccount}
                >
                  {deleting ? t("deleting") : t("permanentlyDelete")}
                </Button>
                <Button variant="outline" onClick={() => { setShowDeleteSection(false); setDeleteConfirm(""); setDeletePassword(""); }}>
                  {tc("cancel")}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      <dialog.DialogComponent />
    </div>
  );
}

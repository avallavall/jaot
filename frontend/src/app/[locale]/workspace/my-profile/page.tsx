"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useDialog } from "@/components/ui/dialog-custom";
import {
  User,
  Building2,
  Star,
  Save,
  ExternalLink,
  Calendar,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { useGuidance } from "@/contexts/GuidanceContext";
import { SkillLevelSelector } from "@/components/guidance/SkillLevelSelector";
import { AccountDataSection } from "@/components/account/AccountDataSection";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import type { UserProfile, SkillLevel } from "@/lib/types";

type UserPublicProfile = UserProfile & { created_at: string };

export default function MyProfilePage() {
  const dialog = useDialog();
  const { user } = useAuth();
  const t = useTranslations("workspace.myProfile");

  const [profile, setProfile] = useState<UserPublicProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Edit form
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [twitterUrl, setTwitterUrl] = useState("");

  const { skillLevel, setSkillLevel } = useGuidance();

  const handleSkillLevelChange = async (level: SkillLevel) => {
    await setSkillLevel(level);
    toast.success(t("skillLevelUpdated"));
  };

  useEffect(() => {
    if (user) {
      loadProfile();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const loadProfile = async () => {
    if (!user) return;
    setLoading(true);
    try {
      const profileData = await api.getUserProfile(user.id);
      setProfile(profileData as unknown as UserPublicProfile);
      setDisplayName(profileData.display_name || profileData.name || "");
      setBio(profileData.bio || "");
      setLinkedinUrl(profileData.linkedin_url || "");
      setTwitterUrl(profileData.twitter_url || "");
    } catch {
      // If public profile fails, use data from auth context
      if (user) {
        setProfile({
          id: user.id,
          name: user.name,
          display_name: user.name,
          slug: "",
          organization_id: "",
          organization_name: "",
          organization_verified: false,
          created_at: new Date().toISOString(),
          total_reviews: 0,
          avg_rating_given: 0,
        });
        setDisplayName(user.name || "");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateUserProfile({
        display_name: displayName || undefined,
        bio: bio || undefined,
        linkedin_url: linkedinUrl || undefined,
        twitter_url: twitterUrl || undefined,
      });
      dialog.showSuccess(t("profileSaved"), t("profileSavedMessage"));
      loadProfile();
    } catch (err) {
      dialog.showError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
    });
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg">
          {t("failedToLoad")}
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold">{t("title")}</h1>
        <Link
          href={`/user/${profile.id}`}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("viewPublicProfile")}
          <ExternalLink className="w-4 h-4" />
        </Link>
      </div>

      <div className="bg-card border rounded-lg p-6 mb-6">
        <div className="flex items-start gap-4">
          <div className="w-20 h-20 bg-muted rounded-full flex items-center justify-center flex-shrink-0">
            <User className="w-10 h-10 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <h2 className="text-xl font-semibold">
              {profile.display_name || profile.name}
            </h2>
            <Link
              href={`/org/${profile.organization_id}`}
              className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            >
              <Building2 className="w-4 h-4" />
              {profile.organization_name}
            </Link>
            <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                {t("memberSince", { date: formatDate(profile.created_at) })}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mt-6 pt-4 border-t">
          <div className="text-center">
            <div className="text-2xl font-bold text-primary">
              {profile.total_reviews}
            </div>
            <div className="text-sm text-muted-foreground">
              {t("reviewsWritten")}
            </div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-primary flex items-center justify-center gap-1">
              {profile.avg_rating_given ? (
                <>
                  <Star className="w-5 h-5 fill-current" />
                  {profile.avg_rating_given.toFixed(1)}
                </>
              ) : (
                "\u2014"
              )}
            </div>
            <div className="text-sm text-muted-foreground">
              {t("avgRatingGiven")}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6">
        <h3 className="text-lg font-semibold mb-4">{t("editProfile")}</h3>

        <div className="space-y-4">
          <div>
            <label
              htmlFor="myprofile-display-name"
              className="block text-sm font-medium mb-1"
            >
              {t("displayName")}
            </label>
            <Input
              id="myprofile-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("displayNamePlaceholder")}
            />
          </div>

          <div>
            <label
              htmlFor="myprofile-bio"
              className="block text-sm font-medium mb-1"
            >
              {t("bio")}
            </label>
            <Textarea
              id="myprofile-bio"
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder={t("bioPlaceholder")}
              rows={3}
            />
          </div>

          <div>
            <label
              htmlFor="myprofile-linkedin"
              className="block text-sm font-medium mb-1"
            >
              {t("linkedinUrl")}
            </label>
            <Input
              id="myprofile-linkedin"
              value={linkedinUrl}
              onChange={(e) => setLinkedinUrl(e.target.value)}
              placeholder={t("linkedinPlaceholder")}
            />
          </div>

          <div>
            <label
              htmlFor="myprofile-twitter"
              className="block text-sm font-medium mb-1"
            >
              {t("twitterUrl")}
            </label>
            <Input
              id="myprofile-twitter"
              value={twitterUrl}
              onChange={(e) => setTwitterUrl(e.target.value)}
              placeholder={t("twitterPlaceholder")}
            />
          </div>

          <Button onClick={handleSave} disabled={saving} className="w-full">
            <Save className="w-4 h-4 mr-2" />
            {saving ? t("saving") : t("saveChanges")}
          </Button>
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6 mt-6">
        <h3 className="text-lg font-semibold mb-2">
          {t("guidancePreferences")}
        </h3>
        <p className="text-sm text-muted-foreground mb-4">
          {t("guidanceDescription")}
        </p>
        <SkillLevelSelector
          value={skillLevel}
          onChange={handleSkillLevelChange}
        />
      </div>

      <AccountDataSection />

      <dialog.DialogComponent />
    </div>
  );
}

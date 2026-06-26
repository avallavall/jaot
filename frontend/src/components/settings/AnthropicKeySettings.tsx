"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { KeyRound } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { AnthropicKeyStatus } from "@/lib/llm-types";

/**
 * BYOK: manage the organization's own Anthropic API key.
 *
 * When set, all of the org's AI calls run on its own Anthropic account (free of
 * JAOT credits, independent of the platform's shared budget). Only the org owner
 * can set or clear the key; other members see read-only status. The plaintext key
 * is never displayed back — only a masked hint to the owner.
 */
export function AnthropicKeySettings() {
  const t = useTranslations("settings.byok");
  const { user } = useAuth();
  const isOwner = user?.is_org_owner ?? false;

  const [status, setStatus] = useState<AnthropicKeyStatus | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.getOrgAnthropicKey());
    } catch {
      setStatus({ enabled: false, hint: null });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      const next = await api.setOrgAnthropicKey(value.trim());
      setStatus(next);
      setValue("");
    } catch {
      setError(t("invalid"));
    } finally {
      setBusy(false);
    }
  }, [value, t]);

  const remove = useCallback(async () => {
    setError(null);
    setBusy(true);
    try {
      setStatus(await api.clearOrgAnthropicKey());
    } catch {
      setError(t("removeFailed"));
    } finally {
      setBusy(false);
    }
  }, [t]);

  const enabled = status?.enabled ?? false;

  return (
    <Card className="border-border">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <KeyRound className="h-4 w-4" />
          </div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold text-foreground">{t("title")}</h2>
            <p className="text-sm text-muted-foreground max-w-prose">{t("description")}</p>
          </div>
        </div>

        <div className="rounded-md border border-border bg-muted/30 p-3">
          {enabled ? (
            <p className="text-sm text-foreground">
              <span className="font-medium text-green-700 dark:text-green-400">
                {t("active")}
              </span>
              {status?.hint && (
                <span className="ml-2 font-mono text-xs text-muted-foreground">{status.hint}</span>
              )}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">{t("inactive")}</p>
          )}
        </div>

        {isOwner ? (
          <div className="space-y-3">
            {!enabled && (
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  type="password"
                  autoComplete="off"
                  placeholder={t("placeholder")}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="font-mono"
                />
                <Button onClick={save} disabled={busy || value.trim().length < 8}>
                  {busy ? t("saving") : t("save")}
                </Button>
              </div>
            )}
            {enabled && (
              <Button variant="outline" onClick={remove} disabled={busy}>
                {busy ? t("removing") : t("remove")}
              </Button>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <p className="text-xs text-muted-foreground">{t("securityNote")}</p>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t("ownerOnly")}</p>
        )}
      </CardContent>
    </Card>
  );
}

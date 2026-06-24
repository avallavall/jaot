"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Shield, Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import type { VerificationRequestStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function VerificationRequest() {
  const t = useTranslations("seller.verification");

  const [status, setStatus] = useState<VerificationRequestStatus | null | undefined>(
    undefined
  );
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    api
      .getVerificationStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, []);

  const handleRequest = async () => {
    setRequesting(true);
    try {
      const result = await api.requestVerification();
      setStatus(result);
    } catch {
      // Error handled by API client
    } finally {
      setRequesting(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-6">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Shield className="w-4 h-4" />
          {t("title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {(status === null || status === undefined) && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {t("requestDescription")}
            </p>
            <Button
              onClick={handleRequest}
              disabled={requesting}
              variant="outline"
              className="gap-2"
            >
              {requesting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Shield className="w-4 h-4" />
              )}
              {t("requestVerification")}
            </Button>
          </div>
        )}

        {status?.status === "pending" && (
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="gap-1">
              <Clock className="w-3 h-3" />
              {t("verificationPending")}
            </Badge>
          </div>
        )}

        {status?.status === "approved" && (
          <div className="flex items-center gap-2">
            <Badge variant="default" className="gap-1">
              <CheckCircle2 className="w-3 h-3" />
              {t("verified")}
            </Badge>
          </div>
        )}

        {status?.status === "rejected" && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge variant="destructive" className="gap-1">
                <XCircle className="w-3 h-3" />
                {t("rejected")}
              </Badge>
            </div>
            {status.admin_note && (
              <p className="text-sm text-muted-foreground">
                {t("rejectedNote")}: {status.admin_note}
              </p>
            )}
            <Button
              onClick={handleRequest}
              disabled={requesting}
              variant="outline"
              size="sm"
              className="gap-2"
            >
              {requesting && <Loader2 className="w-4 h-4 animate-spin" />}
              {t("reRequest")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

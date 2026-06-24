"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import type { AdminVerificationEntry } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface VerificationQueueProps {
  requests: AdminVerificationEntry[];
  onUpdate: () => void;
}

export function VerificationQueue({ requests, onUpdate }: VerificationQueueProps) {
  const t = useTranslations("admin.marketplace");
  const [deciding, setDeciding] = useState<string | null>(null);
  const [adminNote, setAdminNote] = useState("");

  const handleDecide = async (
    id: string,
    status: "approved" | "rejected"
  ) => {
    setDeciding(id);
    try {
      await api.decideVerification(id, {
        status,
        admin_note: adminNote || undefined,
      });
      setAdminNote("");
      onUpdate();
    } catch {
      // Error handled by API client
    } finally {
      setDeciding(null);
    }
  };

  if (requests.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {t("noRequests")}
      </div>
    );
  }

  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("orgName")}</TableHead>
            <TableHead className="text-right">
              {t("profileCompleteness")}
            </TableHead>
            <TableHead className="text-right">
              {t("modelsPublished")}
            </TableHead>
            <TableHead>{t("memberSince")}</TableHead>
            <TableHead>{t("requestDate")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead className="text-right">{/* Actions */}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {requests.map((r) => (
            <TableRow key={r.id}>
              <TableCell className="font-medium">{r.org_name}</TableCell>
              <TableCell className="text-right">
                {Math.round(r.profile_completeness * 100)}%
              </TableCell>
              <TableCell className="text-right">
                {r.models_published}
              </TableCell>
              <TableCell>{r.member_since}</TableCell>
              <TableCell>
                {new Date(r.created_at).toLocaleDateString()}
              </TableCell>
              <TableCell>
                <Badge variant="secondary">{t("pending")}</Badge>
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-2">
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button
                        variant="default"
                        size="sm"
                        disabled={deciding === r.id}
                      >
                        <CheckCircle2 className="w-3 h-3 mr-1" />
                        {t("approve")}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-sm">
                      <DialogHeader>
                        <DialogTitle>{t("approve")}: {r.org_name}</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-3">
                        <Textarea
                          placeholder={t("adminNote")}
                          value={adminNote}
                          onChange={(e) => setAdminNote(e.target.value)}
                          rows={3}
                        />
                        <Button
                          onClick={() => handleDecide(r.id, "approved")}
                          disabled={deciding === r.id}
                          className="w-full"
                        >
                          {deciding === r.id && (
                            <Loader2 className="w-4 h-4 animate-spin mr-1" />
                          )}
                          {t("approve")}
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>

                  <Dialog>
                    <DialogTrigger asChild>
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={deciding === r.id}
                      >
                        <XCircle className="w-3 h-3 mr-1" />
                        {t("reject")}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-sm">
                      <DialogHeader>
                        <DialogTitle>{t("reject")}: {r.org_name}</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-3">
                        <Textarea
                          placeholder={t("adminNote")}
                          value={adminNote}
                          onChange={(e) => setAdminNote(e.target.value)}
                          rows={3}
                        />
                        <Button
                          variant="destructive"
                          onClick={() => handleDecide(r.id, "rejected")}
                          disabled={deciding === r.id}
                          className="w-full"
                        >
                          {deciding === r.id && (
                            <Loader2 className="w-4 h-4 animate-spin mr-1" />
                          )}
                          {t("reject")}
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

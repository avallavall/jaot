"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Ban, Clock, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import type { AdminPlacement } from "@/lib/types";
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
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface ActivePromotionsProps {
  placements: AdminPlacement[];
  onUpdate: () => void;
}

export function ActivePromotions({ placements, onUpdate }: ActivePromotionsProps) {
  const t = useTranslations("admin.marketplace");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [extending, setExtending] = useState<string | null>(null);
  const [extendDays, setExtendDays] = useState<number>(7);

  const handleRevoke = async (id: string) => {
    setRevoking(id);
    try {
      await api.revokePromotion(id);
      onUpdate();
    } catch {
      // Error handled by API client
    } finally {
      setRevoking(null);
    }
  };

  const handleExtend = async (id: string) => {
    setExtending(id);
    try {
      await api.extendPromotion(id, extendDays);
      onUpdate();
    } catch {
      // Error handled by API client
    } finally {
      setExtending(null);
    }
  };

  if (placements.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        {t("noPromotions")}
      </div>
    );
  }

  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("modelName")}</TableHead>
            <TableHead>{t("sellerName")}</TableHead>
            <TableHead>{t("type")}</TableHead>
            <TableHead className="text-right">{t("creditsPaid")}</TableHead>
            <TableHead>{t("startDate")}</TableHead>
            <TableHead>{t("endDate")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead className="text-right">{/* Actions */}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {placements.map((p) => (
            <TableRow key={p.id}>
              <TableCell className="font-medium">
                {p.model_name ?? "--"}
              </TableCell>
              <TableCell>{p.org_name ?? "--"}</TableCell>
              <TableCell>
                <Badge variant="outline">
                  {p.placement_type.replace(/_/g, " ")}
                </Badge>
              </TableCell>
              <TableCell className="text-right">{p.credits_paid}</TableCell>
              <TableCell>
                {new Date(p.starts_at).toLocaleDateString()}
              </TableCell>
              <TableCell>
                {new Date(p.expires_at).toLocaleDateString()}
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    p.status === "active"
                      ? "default"
                      : p.status === "revoked"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {p.status}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-2">
                  {p.status === "active" && (
                    <>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleRevoke(p.id)}
                        disabled={revoking === p.id}
                      >
                        {revoking === p.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Ban className="w-3 h-3" />
                        )}
                        <span className="ml-1">{t("revoke")}</span>
                      </Button>

                      <Dialog>
                        <DialogTrigger asChild>
                          <Button variant="outline" size="sm">
                            <Clock className="w-3 h-3 mr-1" />
                            {t("extend")}
                          </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-xs">
                          <DialogHeader>
                            <DialogTitle>{t("extendDays")}</DialogTitle>
                          </DialogHeader>
                          <div className="space-y-3">
                            <Input
                              type="number"
                              min={1}
                              max={90}
                              value={extendDays}
                              onChange={(e) =>
                                setExtendDays(parseInt(e.target.value) || 7)
                              }
                            />
                            <Button
                              onClick={() => handleExtend(p.id)}
                              disabled={extending === p.id}
                              className="w-full"
                            >
                              {extending === p.id && (
                                <Loader2 className="w-4 h-4 animate-spin mr-1" />
                              )}
                              {t("extend")}
                            </Button>
                          </div>
                        </DialogContent>
                      </Dialog>
                    </>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

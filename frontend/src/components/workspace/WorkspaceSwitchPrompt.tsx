"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// useWorkspaceScopeGuard hook

/**
 * Detects when a URL-embedded workspace ID differs from the active workspace
 * and presents a prompt to switch. Returns dialog state and handlers.
 */
export function useWorkspaceScopeGuard(urlWorkspaceId: string | null) {
  const { activeWorkspaceId, setActiveWorkspace } = useAuth();
  const [showPrompt, setShowPrompt] = useState(false);
  const [targetWorkspaceId, setTargetWorkspaceId] = useState<string | null>(null);
  const [targetWorkspaceName, setTargetWorkspaceName] = useState<string>("");

  useEffect(() => {
    if (urlWorkspaceId && urlWorkspaceId !== activeWorkspaceId) {
      let cancelled = false;
      api
        .getWorkspace(urlWorkspaceId)
        .then((ws) => { if (!cancelled) { setTargetWorkspaceId(urlWorkspaceId); setTargetWorkspaceName(ws.name); setShowPrompt(true); } })
        .catch(() => { if (!cancelled) { setTargetWorkspaceId(urlWorkspaceId); setTargetWorkspaceName(urlWorkspaceId); setShowPrompt(true); } });
      return () => { cancelled = true; };
    }
  }, [urlWorkspaceId, activeWorkspaceId]);

  const handleAccept = async () => {
    if (targetWorkspaceId) {
      await setActiveWorkspace(targetWorkspaceId);
    }
    setShowPrompt(false);
  };

  const handleDecline = () => {
    setShowPrompt(false);
  };

  return { showPrompt, targetWorkspaceName, handleAccept, handleDecline };
}

// WorkspaceSwitchPrompt component

interface WorkspaceSwitchPromptProps {
  open: boolean;
  workspaceName: string;
  onAccept: () => void;
  onDecline: () => void;
}

export function WorkspaceSwitchPrompt({
  open,
  workspaceName,
  onAccept,
  onDecline,
}: WorkspaceSwitchPromptProps) {
  const t = useTranslations("workspace.switchPrompt");
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onDecline()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            {t.rich("description", {
              name: workspaceName,
              b: (chunks) => <strong>{chunks}</strong>,
            })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onDecline}>
            {t("stayHere")}
          </Button>
          <Button onClick={onAccept}>{t("switchWorkspace")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

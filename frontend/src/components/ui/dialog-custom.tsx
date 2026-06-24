"use client";

import { useState } from "react";
import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "./dialog";

interface CustomDialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  message: string;
  type?: "info" | "success" | "error" | "warning";
  confirmText?: string;
  cancelText?: string;
  onConfirm?: () => void;
  showCancel?: boolean;
}

const icons: Record<string, string> = {
  info: "\u2139\uFE0F",
  success: "\u2713",
  error: "\u2717",
  warning: "\u26A0",
};

const colors: Record<string, string> = {
  info: "text-primary",
  success: "text-green-600",
  error: "text-destructive",
  warning: "text-yellow-600",
};

export function CustomDialog({
  open,
  onClose,
  title,
  message,
  type = "info",
  confirmText = "Accept",
  cancelText = "Cancel",
  onConfirm,
  showCancel = false,
}: CustomDialogProps) {
  const defaultTitle =
    type === "error"
      ? "Error"
      : type === "success"
        ? "Success"
        : type === "warning"
          ? "Warning"
          : "Notice";

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <span className={`text-2xl ${colors[type]}`}>{icons[type]}</span>
            {title || defaultTitle}
          </DialogTitle>
        </DialogHeader>
        <DialogDescription className="text-muted-foreground">
          {message}
        </DialogDescription>
        <DialogFooter>
          {showCancel && (
            <Button variant="outline" onClick={onClose}>
              {cancelText}
            </Button>
          )}
          <Button
            onClick={() => {
              onConfirm?.();
              onClose();
            }}
            className={type === "error" ? "bg-destructive hover:bg-destructive/90" : ""}
          >
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Hook for easy dialog management
interface DialogState {
  open: boolean;
  title?: string;
  message: string;
  type: "info" | "success" | "error" | "warning";
  onConfirm?: () => void;
  onCancel?: () => void;
  showCancel?: boolean;
}

export function useDialog() {
  const [state, setState] = useState<DialogState>({
    open: false,
    message: "",
    type: "info",
  });

  const showDialog = (options: Omit<DialogState, "open">) => {
    setState({ ...options, open: true });
  };

  const hideDialog = () => {
    setState((prev) => ({ ...prev, open: false }));
  };

  const showError = (message: string, title?: string) => {
    showDialog({ message, title, type: "error" });
  };

  const showSuccess = (message: string, title?: string) => {
    showDialog({ message, title, type: "success" });
  };

  const showInfo = (message: string, title?: string) => {
    showDialog({ message, title, type: "info" });
  };

  const showWarning = (message: string, title?: string) => {
    showDialog({ message, title, type: "warning" });
  };

  // Promise-based confirm dialog
  const confirm = (message: string, title?: string): Promise<boolean> => {
    return new Promise((resolve) => {
      showDialog({
        message,
        title,
        type: "warning",
        showCancel: true,
        onConfirm: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  };

  // Callback-based confirm (legacy)
  const confirmCallback = (message: string, onConfirm: () => void, title?: string) => {
    showDialog({ message, title, type: "warning", onConfirm, showCancel: true });
  };

  return {
    state,
    showDialog,
    hideDialog,
    showError,
    showSuccess,
    showInfo,
    showWarning,
    confirm,
    confirmCallback,
    DialogComponent: () => (
      <CustomDialog
        open={state.open}
        onClose={() => {
          state.onCancel?.();
          hideDialog();
        }}
        title={state.title}
        message={state.message}
        type={state.type}
        onConfirm={state.onConfirm}
        showCancel={state.showCancel}
      />
    ),
  };
}

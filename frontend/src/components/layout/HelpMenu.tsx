"use client";

import { useState, useEffect, useRef } from "react";
import { HelpCircle, MessageSquare, Bug, BookOpen, Mail, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { fetchCommunityStatus, FEEDBACK_URL, type CommunityStatus } from "@/lib/community";

export function HelpMenu() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<CommunityStatus | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const fetchedRef = useRef(false);
  const t = useTranslations("common");

  useEffect(() => {
    if (open && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchCommunityStatus().then(setStatus);
    }
  }, [open]);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  return (
    <div className="relative" ref={menuRef}>
      <Button
        variant="ghost"
        size="icon"
        className="text-sidebar-foreground/75 hover:text-sidebar-foreground"
        onClick={() => setOpen(!open)}
        aria-label={t("help.helpAndResources")}
        aria-expanded={open}
      >
        <HelpCircle className="w-4 h-4" />
      </Button>

      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-56 rounded-md border bg-popover p-1 shadow-md z-50">
          <p className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
            {t("help.title")}
          </p>

          {/* Community links (conditional) */}
          {status?.discourse_enabled && (
            <a
              href={`${status.discourse_url}/session/sso`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
              onClick={() => setOpen(false)}
            >
              <MessageSquare className="w-4 h-4" />
              {t("help.communityForum")}
              <ExternalLink className="w-3 h-3 ml-auto text-muted-foreground" />
            </a>
          )}

          {/* GitHub Issues for feedback and bug reports */}
          <a
            href={FEEDBACK_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            onClick={() => setOpen(false)}
          >
            <Bug className="w-4 h-4" />
            {t("help.feedbackAndBugs")}
            <ExternalLink className="w-3 h-3 ml-auto text-muted-foreground" />
          </a>

          <a
            href="https://docs.jaot.io"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            onClick={() => setOpen(false)}
          >
            <BookOpen className="w-4 h-4" />
            {t("help.documentation")}
            <ExternalLink className="w-3 h-3 ml-auto text-muted-foreground" />
          </a>

          <a
            href="mailto:support@jaot.io"
            className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            onClick={() => setOpen(false)}
          >
            <Mail className="w-4 h-4" />
            {t("help.contactSupport")}
          </a>
        </div>
      )}
    </div>
  );
}

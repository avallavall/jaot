"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const t = useTranslations("common");

  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" className="text-sidebar-foreground/75" aria-label={t("theme.toggleTheme")}>
        <Sun className="w-4 h-4" />
      </Button>
    );
  }

  const label = theme === "dark" ? t("theme.switchToLight") : t("theme.switchToDark");

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="text-sidebar-foreground/75 hover:text-sidebar-foreground"
      title={label}
      aria-label={label}
    >
      {theme === "dark" ? (
        <Sun className="w-4 h-4" />
      ) : (
        <Moon className="w-4 h-4" />
      )}
    </Button>
  );
}

"use client";

import { useLocale, useTranslations } from "next-intl";
import { Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { getPathname, usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";

/**
 * Native locale display names with proper diacritics.
 * Sorted alphabetically by native name at render time.
 */
const LOCALE_NAMES: Record<string, string> = {
  en: "English",
  es: "Español",
  ca: "Català",
  fr: "Français",
  de: "Deutsch",
};

/** Locales sorted alphabetically by native display name */
const SORTED_LOCALES = [...routing.locales].sort((a, b) =>
  (LOCALE_NAMES[a] ?? a).localeCompare(LOCALE_NAMES[b] ?? b)
);

interface LanguageSwitcherProps {
  /** Optional callback fired after locale switch (e.g., backend sync) */
  onLocaleChange?: (locale: string) => void;
}

export function LanguageSwitcher({ onLocaleChange }: LanguageSwitcherProps) {
  const locale = useLocale();
  const t = useTranslations("common");
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  const handleLocaleChange = (newLocale: string) => {
    // `usePathname` gives the path and nothing else, so switching language on
    // /solve/executions/compare?a=…&b=… landed on the same page with no query
    // string and a line telling the reader to add ?a={id}&b={id} to the URL —
    // the comparison they were reading was simply gone. The search and the
    // hash come off the address bar, which is where they still are.
    const search = typeof window === "undefined" ? "" : window.location.search;
    const hash = typeof window === "undefined" ? "" : window.location.hash;
    if (newLocale === routing.defaultLocale && newLocale !== locale) {
      // English has no prefix, so the client router went to "/..." and reused a
      // redirect it had cached under the old cookie ("/" -> "/de"): switching
      // from German to English stayed on German. A full load through "/en/..."
      // lets the server store the new cookie and drop the prefix.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a full load is the point
      window.location.assign(
        `${getPathname({ href: pathname, locale: newLocale, forcePrefix: true })}${search}${hash}`,
      );
    } else {
      router.replace(`${pathname}${search}${hash}`, { locale: newLocale });
    }
    onLocaleChange?.(newLocale);

    // Fire-and-forget backend sync for authenticated users
    if (isAuthenticated) {
      api.updateUserProfile({ locale: newLocale }).catch(() => {
        // Silently ignore -- locale cookie is the primary persistence mechanism
      });
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {/* The visible text is only the code ("EN"), which says nothing about
            what the button does. The name says it and spells the language out. */}
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5"
          aria-label={t("languageSwitcher.label", { language: LOCALE_NAMES[locale] ?? locale })}
        >
          <Globe className="h-4 w-4" aria-hidden="true" />
          <span className="text-xs uppercase">{locale}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-72 overflow-y-auto">
        {SORTED_LOCALES.map((loc) => (
          <DropdownMenuItem
            key={loc}
            onClick={() => handleLocaleChange(loc)}
            className={loc === locale ? "font-medium" : undefined}
          >
            {LOCALE_NAMES[loc] ?? loc}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

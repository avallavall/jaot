"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import { Tabs } from "radix-ui";
import { cn } from "@/lib/utils";
import { Copy, Check } from "lucide-react";

const STORAGE_KEY = "docs-code-tab";
const DEFAULT_TAB = "python";

interface CodeTabContextValue {
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

const CodeTabContext = createContext<CodeTabContextValue>({
  activeTab: DEFAULT_TAB,
  setActiveTab: () => {},
});

export function CodeTabProvider({ children }: { children: React.ReactNode }) {
  const [activeTab, setActiveTabState] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(STORAGE_KEY) || DEFAULT_TAB;
    }
    return DEFAULT_TAB;
  });

  const setActiveTab = useCallback((tab: string) => {
    setActiveTabState(tab);
    localStorage.setItem(STORAGE_KEY, tab);
  }, []);

  return (
    <CodeTabContext.Provider value={{ activeTab, setActiveTab }}>
      {children}
    </CodeTabContext.Provider>
  );
}

const LANGUAGE_LABELS: Record<string, string> = {
  python: "Python",
  javascript: "JavaScript",
  js: "JavaScript",
  typescript: "TypeScript",
  ts: "TypeScript",
  curl: "cURL",
  bash: "cURL",
  shell: "Shell",
};

function getLanguageLabel(lang: string): string {
  return LANGUAGE_LABELS[lang.toLowerCase()] || lang;
}

interface TabData {
  language: string;
  code: string;
}

function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 rounded-md bg-muted/80 opacity-0 group-hover:opacity-100 transition-opacity"
      aria-label="Copy code"
    >
      {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

export function CodeTabs({ tabs }: { tabs: TabData[] }) {
  const { activeTab, setActiveTab } = useContext(CodeTabContext);
  const [highlightedHtml, setHighlightedHtml] = useState<Record<string, string>>({});
  const containerRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!tabs || tabs.length === 0) return;

    let cancelled = false;

    async function highlight() {
      const { codeToHtml } = await import("shiki");
      const result: Record<string, string> = {};

      for (const tab of tabs) {
        const lang = tab.language === "curl" ? "bash" : tab.language;
        result[tab.language] = await codeToHtml(tab.code, {
          lang,
          themes: {
            light: "github-light",
            dark: "github-dark-dimmed",
          },
          defaultColor: false,
        });
      }

      if (!cancelled) {
        setHighlightedHtml(result);
      }
    }

    highlight();
    return () => { cancelled = true; };
  }, [tabs]);

  if (!tabs || tabs.length === 0) {
    return null;
  }

  const languages = tabs.map((t) => t.language);
  const currentTab = languages.includes(activeTab) ? activeTab : languages[0];

  return (
    <Tabs.Root
      value={currentTab}
      onValueChange={setActiveTab}
      className="not-prose my-4"
    >
      <Tabs.List className="flex border-b border-border bg-muted/30 rounded-t-lg">
        {tabs.map(({ language }) => (
          <Tabs.Trigger
            key={language}
            value={language}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors",
              "text-muted-foreground hover:text-foreground",
              "border-b-2 border-transparent",
              "data-[state=active]:border-primary data-[state=active]:text-foreground"
            )}
          >
            {getLanguageLabel(language)}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {tabs.map(({ language, code }) => (
        <Tabs.Content key={language} value={language} className="mt-0 relative group">
          {highlightedHtml[language] ? (
            <div
              ref={(el) => { containerRefs.current[language] = el; }}
              dangerouslySetInnerHTML={{ __html: highlightedHtml[language] }}
              className="[&_pre]:overflow-x-auto [&_pre]:p-4 [&_pre]:rounded-b-lg [&_pre]:bg-[var(--shiki-light-bg,#fff)] dark:[&_pre]:bg-[var(--shiki-dark-bg,#22272e)]"
            />
          ) : (
            <pre className="overflow-x-auto p-4 rounded-b-lg bg-muted">
              <code>{code}</code>
            </pre>
          )}
          <CopyButton code={code} />
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}

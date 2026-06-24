"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Dialog } from "radix-ui";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { searchDocs, type SearchEntry } from "@/lib/docs/search-index";

export function SearchModal() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchEntry[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();

  // Global Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Debounced search
  const handleSearch = useCallback((value: string) => {
    setQuery(value);
    setSelectedIndex(0);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (!value.trim()) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      const matches = await searchDocs(value);
      setResults(matches);
      setSelectedIndex(0);
    }, 200);
  }, []);

  // Navigate to selected result
  const navigateToResult = useCallback(
    (result: SearchEntry) => {
      router.push(`/docs/${result.slug}`);
      setOpen(false);
      setQuery("");
      setResults([]);
    },
    [router]
  );

  // Keyboard navigation within results
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter" && results[selectedIndex]) {
        e.preventDefault();
        navigateToResult(results[selectedIndex]);
      }
    },
    [results, selectedIndex, navigateToResult]
  );

  // Reset state when dialog closes
  const handleOpenChange = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
    }
  }, []);

  // Highlight matched terms in text
  function highlightMatch(text: string, q: string): React.ReactNode {
    if (!q.trim() || !text) return text;
    const regex = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    const parts = text.split(regex);
    return parts.map((part, i) =>
      regex.test(part) ? (
        <span key={i} className="font-semibold text-foreground">
          {part}
        </span>
      ) : (
        part
      )
    );
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Trigger asChild>
        <button
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground border border-border rounded-lg hover:bg-accent transition-colors w-full"
          aria-label="Search documentation"
        >
          <Search className="h-4 w-4" />
          <span className="flex-1 text-left">Search docs...</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 rounded border border-border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            <span className="text-xs">
              {typeof navigator !== "undefined" &&
              /Mac|iPod|iPhone|iPad/.test(navigator.platform || "")
                ? "Cmd"
                : "Ctrl"}
            </span>
            +K
          </kbd>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className="fixed left-[50%] top-[20%] z-50 w-full max-w-lg translate-x-[-50%] rounded-xl border border-border bg-background shadow-lg"
          onKeyDown={handleKeyDown}
        >
          <Dialog.Title className="sr-only">Search documentation</Dialog.Title>
          <Dialog.Description className="sr-only">
            Type to search across all documentation pages
          </Dialog.Description>

          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <Search className="h-4 w-4 text-muted-foreground shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="Type to search documentation..."
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              autoFocus
            />
            {query && (
              <button
                onClick={() => {
                  setQuery("");
                  setResults([]);
                  inputRef.current?.focus();
                }}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto py-2">
            {!query.trim() && (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                Type to search documentation...
              </p>
            )}

            {query.trim() && results.length === 0 && (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                No results found for &quot;{query}&quot;
              </p>
            )}

            {results.map((result, i) => (
              <button
                key={result.id}
                onClick={() => navigateToResult(result)}
                className={`w-full text-left px-4 py-3 flex flex-col gap-1 transition-colors ${
                  i === selectedIndex
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50"
                }`}
                onMouseEnter={() => setSelectedIndex(i)}
              >
                <span className="text-sm font-medium">
                  {highlightMatch(result.title, query)}
                </span>
                <span className="text-xs text-muted-foreground line-clamp-1">
                  {highlightMatch(result.description, query)}
                </span>
              </button>
            ))}
          </div>

          {results.length > 0 && (
            <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground">
              <span>
                <kbd className="rounded border border-border bg-muted px-1">
                  &uarr;
                </kbd>{" "}
                <kbd className="rounded border border-border bg-muted px-1">
                  &darr;
                </kbd>{" "}
                to navigate
              </span>
              <span>
                <kbd className="rounded border border-border bg-muted px-1">
                  Enter
                </kbd>{" "}
                to select
              </span>
              <span>
                <kbd className="rounded border border-border bg-muted px-1">
                  Esc
                </kbd>{" "}
                to close
              </span>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

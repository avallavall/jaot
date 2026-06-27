import FlexSearch from "flexsearch";

export interface SearchEntry {
  id: number;
  title: string;
  description: string;
  slug: string;
  content: string;
  section: string;
}

// The FlexSearch Document index handle is kept untyped here: its generic
// signature is heavy and we only touch a small dynamic surface (add/search).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let index: any = null;
let entries: SearchEntry[] = [];

export async function getSearchIndex() {
  if (index) return { index, entries };

  const res = await fetch("/search-index.json");
  entries = await res.json();

  index = new FlexSearch.Document({
    document: {
      id: "id",
      index: ["title", "description", "content"],
      store: ["title", "slug", "description", "section"],
    },
    tokenize: "forward",
    resolution: 9,
  });

  for (const entry of entries) {
    index.add(entry);
  }

  return { index, entries };
}

export async function searchDocs(query: string): Promise<SearchEntry[]> {
  if (!query.trim()) return [];

  const { index: idx, entries: allEntries } = await getSearchIndex();
  const results = idx.search(query, { limit: 10, enrich: true });

  // Deduplicate across fields (title, description, content may match same doc)
  const seenIds = new Set<number>();
  const matches: SearchEntry[] = [];

  for (const field of results) {
    for (const result of field.result) {
      const id = typeof result === "object" ? (result as { id: number }).id : result;
      if (!seenIds.has(id as number)) {
        seenIds.add(id as number);
        matches.push(allEntries[id as number]);
      }
    }
  }

  return matches;
}

/** Reset the index (useful for testing) */
export function resetSearchIndex() {
  index = null;
  entries = [];
}

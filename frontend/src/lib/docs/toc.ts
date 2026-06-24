export interface TocItem {
  id: string;
  text: string;
  level: 2 | 3;
}

export function extractTocFromDOM(): TocItem[] {
  const headings = document.querySelectorAll("article h2, article h3");
  const items: TocItem[] = [];

  headings.forEach((heading) => {
    const id = heading.id;
    const text = heading.textContent?.trim() ?? "";
    const level = heading.tagName === "H2" ? 2 : 3;

    if (id && text) {
      items.push({ id, text, level });
    }
  });

  return items;
}

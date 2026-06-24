import matter from "gray-matter";
import fs from "fs";
import path from "path";

interface SearchEntry {
  id: number;
  title: string;
  description: string;
  slug: string;
  content: string;
  section: string;
}

/** Recursively find all .mdx files under a directory */
function findMdxFiles(dir: string, base: string = dir): string[] {
  const results: string[] = [];
  if (!fs.existsSync(dir)) return results;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...findMdxFiles(fullPath, base));
    } else if (entry.name.endsWith(".mdx")) {
      // Return path relative to base directory
      results.push(path.relative(base, fullPath).replace(/\\/g, "/"));
    }
  }
  return results;
}

async function buildSearchIndex() {
  const contentDir = path.resolve(process.cwd(), "content/docs");
  const files = findMdxFiles(contentDir);

  const entries: SearchEntry[] = files.map((file, i) => {
    const raw = fs.readFileSync(path.join(contentDir, file), "utf-8");
    const { data, content } = matter(raw);

    const slug = file.replace(".mdx", "");
    const section = slug.split("/")[0] || "general";

    // Strip MDX/JSX syntax for plain text search
    const plainContent = content
      .replace(/import\s+.*from\s+['"].*['"]/g, "") // import statements
      .replace(/<[^>]+>/g, "") // JSX/HTML tags
      .replace(/```[\s\S]*?```/g, "") // code fences
      .replace(/[#*`_~\[\]]/g, "") // markdown symbols
      .replace(/\n{3,}/g, "\n\n") // collapse multiple newlines
      .trim();

    return {
      id: i,
      title: data.title || "",
      description: data.description || "",
      slug,
      content: plainContent,
      section,
    };
  });

  const outDir = path.resolve(process.cwd(), "public");
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  fs.writeFileSync(
    path.join(outDir, "search-index.json"),
    JSON.stringify(entries, null, 2)
  );

  console.log(`Search index built: ${entries.length} entries`);
  entries.forEach((e) => console.log(`  - ${e.section}/${e.slug}: "${e.title}"`));
}

buildSearchIndex().catch((err) => {
  console.error("Failed to build search index:", err);
  process.exit(1);
});

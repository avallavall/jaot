import { DocsSidebar } from "@/components/docs/DocsSidebar";
import { TableOfContents } from "@/components/docs/TableOfContents";
import { MobileDocsNav } from "@/components/docs/MobileDocsNav";
import { DocsBreadcrumbs } from "@/components/docs/DocsBreadcrumbs";
import { DocsPagination } from "@/components/docs/DocsPagination";
import { SearchModal } from "@/components/docs/SearchModal";
import { CodeTabProvider } from "@/components/docs/CodeTabs";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <CodeTabProvider>
      <div className="grid grid-cols-1 lg:grid-cols-[256px_1fr] xl:grid-cols-[256px_1fr_224px] min-h-[calc(100vh-3.5rem)]">
        <aside className="hidden lg:block sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto border-r border-border">
          <div className="px-3 pt-4 pb-2">
            <SearchModal />
          </div>
          <DocsSidebar />
        </aside>

        <div className="max-w-3xl mx-auto w-full px-8 py-8">
          <DocsBreadcrumbs />
          <article className="prose dark:prose-invert max-w-none">
            {children}
          </article>
          <DocsPagination />
        </div>

        <TableOfContents />
        <MobileDocsNav />
      </div>
    </CodeTabProvider>
  );
}

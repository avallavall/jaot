import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import createMDX from "@next/mdx";
import remarkGfm from "remark-gfm";
import remarkFrontmatter from "remark-frontmatter";
import remarkMdxFrontmatter from "remark-mdx-frontmatter";
import { remarkCodeTabs } from "./lib/remark-code-tabs.mjs";
import rehypePrettyCode from "rehype-pretty-code";
import rehypeSlug from "rehype-slug";
import rehypeAutolinkHeadings from "rehype-autolink-headings";

const withNextIntl = createNextIntlPlugin();

const nextConfig: NextConfig = {
  output: "standalone",
  pageExtensions: ["js", "jsx", "md", "mdx", "ts", "tsx"],
  skipTrailingSlashRedirect: true,
  images: {
    formats: ["image/avif", "image/webp"],
  },
  webpack(config) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require("path");
    config.resolve.alias["@content"] = path.resolve(process.cwd(), "content");
    return config;
  },
  async rewrites() {
    const apiUrl =
      process.env.API_PROXY_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
    return [
      {
        source: "/api/:path(.*)",
        destination: `${apiUrl}/api/:path`,
      },
      // AI discovery documents
      {
        source: "/.well-known/llms.txt",
        destination: `${apiUrl}/.well-known/llms.txt`,
      },
      {
        source: "/.well-known/llms-full.txt",
        destination: `${apiUrl}/.well-known/llms-full.txt`,
      },
      // MCP endpoint
      {
        source: "/mcp",
        destination: `${apiUrl}/api/v2/mcp`,
      },
      {
        source: "/mcp/:path*",
        destination: `${apiUrl}/api/v2/mcp/:path*`,
      },
    ];
  },
};

const withMDX = createMDX({
  options: {
    remarkPlugins: [remarkGfm, remarkFrontmatter, remarkMdxFrontmatter, remarkCodeTabs],
    rehypePlugins: [
      rehypeSlug,
      [rehypeAutolinkHeadings, { behavior: "wrap" }],
      [rehypePrettyCode, {
        theme: { light: "github-light", dark: "github-dark-dimmed" },
        keepBackground: false,
      }],
    ],
  },
});

export default withNextIntl(withMDX(nextConfig));

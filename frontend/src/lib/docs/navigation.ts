export interface DocsNavItem {
  title: string;
  slug?: string;
  children?: DocsNavItem[];
}

export const docsNavigation: DocsNavItem[] = [
  {
    title: "Getting Started",
    children: [
      { title: "Introduction", slug: "getting-started/introduction" },
      { title: "Quick Start", slug: "getting-started/quick-start" },
      { title: "Authentication", slug: "getting-started/authentication" },
    ],
  },
  {
    title: "AI Builder",
    children: [
      { title: "Building with AI", slug: "ai-builder/building-with-ai" },
      { title: "Templates Gallery", slug: "ai-builder/templates-gallery" },
      { title: "Understanding Your Solution", slug: "ai-builder/understanding-your-solution" },
    ],
  },
  {
    title: "Marketplace",
    children: [
      { title: "Browsing Models", slug: "marketplace/browsing-models" },
      { title: "Publishing Models", slug: "marketplace/publishing-models" },
    ],
  },
  {
    title: "MCP Integration",
    children: [
      { title: "Overview", slug: "mcp/overview" },
    ],
  },
  {
    title: "API Reference",
    children: [
      { title: "Solve", slug: "api/solve" },
      { title: "Models", slug: "api/models" },
      { title: "Executions", slug: "api/executions" },
      { title: "Credits & Billing", slug: "api/credits-billing" },
      { title: "API Keys", slug: "api/api-keys" },
      { title: "Notifications", slug: "api/notifications" },
      { title: "Triggers", slug: "api/triggers" },
      { title: "Versions", slug: "api/versions" },
      { title: "Webhooks", slug: "api/webhooks" },
      { title: "Health", slug: "api/health" },
      { title: "Admin", slug: "api/admin" },
      { title: "WebSocket Protocol", slug: "api/websocket" },
    ],
  },
  {
    title: "Reference",
    children: [
      { title: "Error Reference", slug: "reference/errors" },
      { title: "Rate Limits & Credits", slug: "reference/rate-limits-credits" },
    ],
  },
  {
    title: "Guides",
    children: [
      { title: "Guide Portal", slug: "guides/index" },
      // Manufacturing
      { title: "Manufacturing" },
      { title: "Production Planning", slug: "guides/production-planning" },
      { title: "Cutting & Packing", slug: "guides/cutting-and-packing" },
      { title: "Food & Beverage Production", slug: "guides/food-and-beverage" },
      { title: "Textile Manufacturing", slug: "guides/textile-manufacturing" },
      { title: "Chemical Process Optimization", slug: "guides/chemical-process" },
      { title: "Construction Project Planning", slug: "guides/construction-planning" },
      // Finance
      { title: "Finance" },
      { title: "Portfolio Optimization", slug: "guides/portfolio-optimization" },
      { title: "Insurance Risk Modeling", slug: "guides/insurance-risk" },
      { title: "Real Estate Investment", slug: "guides/real-estate-investment" },
      // Logistics
      { title: "Logistics" },
      { title: "Route & Fleet Optimization", slug: "guides/route-and-fleet" },
      { title: "Transportation Network Design", slug: "guides/transportation-network" },
      { title: "Maritime Shipping", slug: "guides/maritime-shipping" },
      { title: "Railway Operations", slug: "guides/railway-operations" },
      { title: "Facility Location", slug: "guides/facility-location" },
      { title: "Warehouse Layout & Operations", slug: "guides/warehouse-operations" },
      // Supply Chain
      { title: "Supply Chain" },
      { title: "Supply Chain Planning", slug: "guides/supply-chain-planning" },
      // Energy & Environment
      { title: "Energy & Environment" },
      { title: "Energy Grid Optimization", slug: "guides/energy-grid" },
      { title: "Environmental Resource Management", slug: "guides/environmental-management" },
      { title: "Water Distribution Networks", slug: "guides/water-distribution" },
      // Healthcare & Pharma
      { title: "Healthcare & Pharma" },
      { title: "Healthcare Resource Allocation", slug: "guides/healthcare-resources" },
      { title: "Pharmaceutical Production", slug: "guides/pharmaceutical-production" },
      // Technology
      { title: "Technology" },
      { title: "Telecom Network Planning", slug: "guides/telecom-network" },
      { title: "Network & Graph Optimization", slug: "guides/network-graph" },
      { title: "Advertising & Media Planning", slug: "guides/advertising-media" },
      // Services
      { title: "Services" },
      { title: "Retail Assortment & Pricing", slug: "guides/retail-assortment" },
      { title: "Workforce Scheduling", slug: "guides/workforce-scheduling" },
      { title: "Sports League Scheduling", slug: "guides/sports-scheduling" },
      { title: "Education Timetabling", slug: "guides/education-timetabling" },
      // Natural Resources
      { title: "Natural Resources" },
      { title: "Agricultural Planning", slug: "guides/agricultural-planning" },
      { title: "Mining Operations", slug: "guides/mining-operations" },
      { title: "Forestry Management", slug: "guides/forestry-management" },
      // Public Sector
      { title: "Public Sector" },
      { title: "Government Resource Allocation", slug: "guides/government-resources" },
      { title: "Aerospace Mission Planning", slug: "guides/aerospace-mission" },
      // General
      { title: "General" },
      { title: "Getting Started with Optimization", slug: "guides/getting-started-optimization" },
    ],
  },
];

export function getFlatPages(): { title: string; slug: string }[] {
  const flat: { title: string; slug: string }[] = [];
  const seen = new Set<string>();
  function walk(items: DocsNavItem[]) {
    for (const item of items) {
      if (item.slug && !seen.has(item.slug)) {
        seen.add(item.slug);
        flat.push({ title: item.title, slug: item.slug });
      }
      if (item.children) walk(item.children);
    }
  }
  walk(docsNavigation);
  return flat;
}

export function getPrevNext(currentSlug: string) {
  const flat = getFlatPages();
  const idx = flat.findIndex((p) => p.slug === currentSlug);
  return {
    prev: idx > 0 ? flat[idx - 1] : null,
    next: idx < flat.length - 1 ? flat[idx + 1] : null,
  };
}

export function getDocsPages() {
  return getFlatPages();
}

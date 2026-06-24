import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildOrganizationSchema, buildWebSiteSchema } from "@/lib/seo/schemas";
import { BASE_URL } from "@/lib/seo/urls";
import {
  ArrowRight,
  Bot,
  Building2,
  Calendar,
  Check,
  Factory,
  GraduationCap,
  Network,
  PieChart,
  Sparkles,
  Store,
  Truck,
  Users,
} from "lucide-react";

// Static per-deployment JSON-LD — built once at module load (BASE_URL is a build-time
// constant), not rebuilt on every SSR render of this high-traffic landing page.
const ORGANIZATION_SCHEMA = buildOrganizationSchema(BASE_URL);
const WEBSITE_SCHEMA = buildWebSiteSchema(BASE_URL);

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  // Root path is the empty string, NOT "/" — this is the convention the rest of the
  // SEO helpers encode (layout.tsx uses buildAlternates(""), every buildAlternates/
  // localizedUrl unit test treats root as ""). Passing "/" makes localizedUrl emit
  // trailing-slash URLs (https://jaot.io/, https://jaot.io/es/, …) which diverge from
  // the layout's slash-less canonical+hreflang and break the home page's per-locale
  // alternates (seo-canonical-hreflang.spec.ts). "" yields the bare base URL per locale.
  return buildPageMetadata({ namespace: "metadata.home", path: "", locale });
}

const HERO_PILLARS = [
  {
    icon: Sparkles,
    key: "aiBuilder",
    cta: { href: "/signup", key: "hero.ctaBuilder" },
  },
  {
    icon: Store,
    key: "marketplace",
    cta: { href: "/marketplace", key: "hero.ctaMarketplace" },
  },
  {
    icon: Bot,
    key: "mcp",
    cta: { href: "/docs/getting-started/introduction", key: "hero.ctaMcp" },
  },
] as const;

const USE_CASE_KEYS = [
  { icon: Truck, key: "vehicleRouting", source: "marketplace" as const },
  { icon: Calendar, key: "employeeScheduling", source: "ai" as const },
  { icon: PieChart, key: "budgetAllocation", source: "ai" as const },
  { icon: Factory, key: "productionPlanning", source: "marketplace" as const },
  { icon: Network, key: "supplyChainNetwork", source: "marketplace" as const },
  { icon: Users, key: "resourceAssignment", source: "ai" as const },
] as const;

const HOW_IT_WORKS_KEYS = ["step1", "step2", "step3"] as const;

export default async function HomePage() {
  const t = await getTranslations("public");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <JsonLd data={ORGANIZATION_SCHEMA} />
      <JsonLd data={WEBSITE_SCHEMA} />

      <section className="max-w-6xl mx-auto px-6 py-24 text-center">
        <Badge variant="outline" className="mb-6 text-sm font-normal px-4 py-1">
          {t("hero.badge")}
        </Badge>
        <h1 className="text-5xl md:text-7xl font-serif text-foreground mb-6 leading-tight">
          {t("hero.titleLine1")}
          <br />
          {t("hero.titleLine2")}
          <br />
          <span className="text-primary">{t("hero.titleLine3")}</span>
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto mb-3">
          {t("hero.subtitle")}
        </p>
        <p className="text-sm text-muted-foreground italic mb-10">
          {t("hero.tagline")}
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl mx-auto mt-12">
          {HERO_PILLARS.map((pillar) => (
            <Card key={pillar.key} className="border-border text-left">
              <CardContent className="pt-6 pb-6">
                <div className="w-10 h-10 rounded-md bg-primary/10 flex items-center justify-center text-primary mb-4">
                  <pillar.icon className="w-5 h-5" />
                </div>
                <p className="font-semibold mb-2">
                  {t(`hero.pillars.${pillar.key}.title`)}
                </p>
                <p className="text-sm text-muted-foreground mb-4">
                  {t(`hero.pillars.${pillar.key}.description`)}
                </p>
                <Link href={pillar.cta.href}>
                  <Button variant="outline" size="sm" className="gap-1.5">
                    {t(pillar.cta.key)}
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Button>
                </Link>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mt-12 flex flex-wrap items-center justify-center gap-3">
          <Badge variant="outline" className="text-xs font-normal px-3 py-1">
            {t("hero.openSourceSolver")}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal px-3 py-1">
            {t("hero.templatesCount")}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal px-3 py-1">
            {t("hero.firstMarketplace")}
          </Badge>
          <Badge variant="outline" className="text-xs font-normal px-3 py-1">
            {t("hero.mcpNative")}
          </Badge>
        </div>
      </section>

      <section className="bg-muted/30 border-y border-border py-24">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-serif mb-4">{t("audience.title")}</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <Card className="border-border">
              <CardContent className="pt-8 pb-8">
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary mb-6">
                  <Building2 className="w-6 h-6" />
                </div>
                <h3 className="text-xl font-serif mb-4">
                  {t("audience.teams.title")}
                </h3>
                <ul className="space-y-3 text-sm text-muted-foreground mb-6">
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.teams.item1")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.teams.item2")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.teams.item3")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.teams.item4")}
                  </li>
                </ul>
                <Link href="/signup">
                  <Button variant="outline" size="sm">
                    {t("audience.teams.cta")}
                  </Button>
                </Link>
              </CardContent>
            </Card>

            <Card className="border-border">
              <CardContent className="pt-8 pb-8">
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary mb-6">
                  <Store className="w-6 h-6" />
                </div>
                <h3 className="text-xl font-serif mb-4">
                  {t("audience.sellers.title")}
                </h3>
                <ul className="space-y-3 text-sm text-muted-foreground mb-6">
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.sellers.item1")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.sellers.item2")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.sellers.item3")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.sellers.item4")}
                  </li>
                </ul>
                <Link href="/for-sellers">
                  <Button variant="outline" size="sm">
                    {t("audience.sellers.cta")}
                  </Button>
                </Link>
              </CardContent>
            </Card>

            <Card className="border-border">
              <CardContent className="pt-8 pb-8">
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary mb-6">
                  <GraduationCap className="w-6 h-6" />
                </div>
                <h3 className="text-xl font-serif mb-4">
                  {t("audience.students.title")}
                </h3>
                <ul className="space-y-3 text-sm text-muted-foreground mb-6">
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.students.item1")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.students.item2")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.students.item3")}
                  </li>
                  <li className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                    {t("audience.students.item4")}
                  </li>
                </ul>
                <Link href="/signup">
                  <Button variant="outline" size="sm">
                    {t("audience.students.cta")}
                  </Button>
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-serif mb-4">{t("useCases.title")}</h2>
          <p className="text-muted-foreground max-w-xl mx-auto">
            {t("useCases.subtitle")}
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {USE_CASE_KEYS.map((uc) => (
            <Card key={uc.key} className="border-border">
              <CardContent className="pt-6">
                <div className="w-10 h-10 rounded-md bg-primary/10 flex items-center justify-center text-primary mb-4">
                  <uc.icon className="w-5 h-5" />
                </div>
                <h3 className="font-semibold mb-2">
                  {t(`useCases.${uc.key}.title`)}
                </h3>
                <p className="text-sm text-muted-foreground mb-3">
                  {t(`useCases.${uc.key}.scenario`)}
                </p>
                <div className="flex flex-wrap items-center gap-2 mb-4">
                  <Badge variant="outline" className="text-xs font-normal whitespace-normal">
                    {t(`useCases.${uc.key}.result`)}
                  </Badge>
                  <Badge
                    variant="secondary"
                    className="text-xs font-normal gap-1 shrink-0"
                  >
                    {uc.source === "ai" ? (
                      <>
                        <Sparkles className="w-3 h-3" />
                        {t("useCases.builtWithAi")}
                      </>
                    ) : (
                      <>
                        <Store className="w-3 h-3" />
                        {t("useCases.fromMarketplace")}
                      </>
                    )}
                  </Badge>
                </div>
                <div className="flex items-center gap-3 mt-4">
                  <Link href="/marketplace">
                    <Button variant="outline" size="sm" className="text-xs">
                      {t("useCases.tryTemplate")}
                    </Button>
                  </Link>
                  <Link
                    href="/signup"
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {t("useCases.getStarted")}
                  </Link>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-serif mb-4">{t("mcp.title")}</h2>
          <p className="text-muted-foreground max-w-xl mx-auto">
            {t("mcp.subtitle")}
          </p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
          <div className="space-y-6">
            {(["discover", "authenticate", "solve", "results"] as const).map(
              (step, idx) => (
                <div key={step} className="flex gap-4">
                  <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm font-semibold shrink-0 mt-0.5">
                    {idx + 1}
                  </div>
                  <div>
                    <h3 className="font-semibold mb-1">
                      {t(`mcp.workflow.${step}.title`)}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      {t(`mcp.workflow.${step}.description`)}
                    </p>
                  </div>
                </div>
              ),
            )}
          </div>

          <Card className="border-border">
            <CardContent className="pt-6 pb-6">
              <h3 className="font-semibold mb-4">{t("mcp.toolsTitle")}</h3>
              <div className="space-y-4">
                {(
                  [
                    {
                      key: "problemSolving",
                      tools: ["solve_problem", "validate_problem"],
                    },
                    {
                      key: "templates",
                      tools: [
                        "list_templates",
                        "get_template",
                        "solve_with_template",
                      ],
                    },
                    {
                      key: "marketplace",
                      tools: [
                        "list_catalog_models",
                        "get_catalog_model",
                        "get_catalog_model_schema",
                        "activate_catalog_model",
                      ],
                    },
                    {
                      key: "execution",
                      tools: ["execute_model", "get_execution"],
                    },
                    { key: "account", tools: ["get_credit_balance"] },
                  ] as const
                ).map((group) => (
                  <div key={group.key}>
                    <p className="text-sm font-medium text-foreground mb-1">
                      {t(`mcp.tools.${group.key}`)}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {group.tools.map((tool) => (
                        <Badge
                          key={tool}
                          variant="secondary"
                          className="text-xs font-mono font-normal"
                        >
                          {tool}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="text-center mt-12">
          <Badge
            variant="outline"
            className="text-sm font-normal px-4 py-1.5 mb-6"
          >
            {t("mcp.agentBadge")}
          </Badge>
          <div className="mt-4">
            <Link href="/docs/getting-started/introduction">
              <Button variant="outline" size="lg" className="gap-2">
                <Bot className="w-4 h-4" />
                {t("mcp.cta")}
                <ArrowRight className="w-4 h-4" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="bg-muted/30 border-y border-border py-24">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-serif mb-4">
              {t("howItWorks.title")}
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {HOW_IT_WORKS_KEYS.map((stepKey, idx) => (
              <div key={stepKey} className="text-center">
                <div className="w-10 h-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm font-semibold mx-auto mb-4">
                  {idx + 1}
                </div>
                <h3 className="font-semibold mb-2">
                  {t(`howItWorks.${stepKey}.title`)}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {t(`howItWorks.${stepKey}.description`)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-muted/30 border-y border-border py-24 text-center">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-serif mb-4">{t("cta.title")}</h2>
          <p className="text-muted-foreground mb-8 max-w-md mx-auto">
            {t("cta.subtitle")}
          </p>
          <Link href="/signup">
            <Button size="lg" className="gap-2 px-10">
              {t("cta.button")}
              <ArrowRight className="w-4 h-4" />
            </Button>
          </Link>
        </div>
      </section>
    </div>
  );
}

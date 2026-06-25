import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Reveal } from "@/components/motion/Reveal";
import { ProductFrame } from "@/components/landing/ProductFrame";
import { SectionHeading } from "@/components/landing/SectionHeading";
import { StatStrip } from "@/components/landing/StatStrip";
import { GITHUB_REPO_URL } from "@/lib/community";
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
  Cpu,
  Factory,
  GraduationCap,
  LayoutTemplate,
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

// Accent identities are pulled from the node-editor palette (defined for both
// themes in globals.css), so the landing visually echoes the product and the
// page stops being monochrome burgundy.
const ACCENT_TERRACOTTA = "--node-objective-selected";
const ACCENT_SAGE = "--node-constraint-selected";
const ACCENT_SEPIA = "--node-variable-selected";

const chipStyle = (accentVar: string) => ({
  color: `var(${accentVar})`,
  backgroundColor: `color-mix(in oklab, var(${accentVar}) 12%, transparent)`,
});

const HERO_PILLARS = [
  {
    icon: Sparkles,
    key: "aiBuilder",
    accent: ACCENT_TERRACOTTA,
    cta: { href: "/signup", key: "hero.ctaBuilder" },
  },
  {
    icon: Store,
    key: "marketplace",
    accent: ACCENT_SAGE,
    cta: { href: "/marketplace", key: "hero.ctaMarketplace" },
  },
  {
    icon: Bot,
    key: "mcp",
    accent: ACCENT_SEPIA,
    cta: { href: "/docs/mcp/overview", key: "hero.ctaMcp" },
  },
] as const;

const AUDIENCE = [
  { icon: Building2, key: "teams", href: "/signup", accent: ACCENT_SEPIA },
  { icon: Store, key: "sellers", href: "/marketplace", accent: ACCENT_TERRACOTTA },
  { icon: GraduationCap, key: "students", href: "/signup", accent: ACCENT_SAGE },
] as const;

const AUDIENCE_ITEMS = ["item1", "item2", "item3", "item4"] as const;

const USE_CASE_KEYS = [
  { icon: Truck, key: "vehicleRouting", source: "marketplace" as const },
  { icon: Calendar, key: "employeeScheduling", source: "ai" as const },
  { icon: PieChart, key: "budgetAllocation", source: "ai" as const },
  { icon: Factory, key: "productionPlanning", source: "marketplace" as const },
  { icon: Network, key: "supplyChainNetwork", source: "marketplace" as const },
  { icon: Users, key: "resourceAssignment", source: "ai" as const },
] as const;

const HOW_IT_WORKS_KEYS = ["step1", "step2", "step3"] as const;

const MCP_TOOL_GROUPS = [
  { key: "problemSolving", tools: ["solve_problem", "validate_problem"] },
  {
    key: "templates",
    tools: ["list_templates", "get_template", "solve_with_template"],
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
  { key: "execution", tools: ["execute_model", "get_execution"] },
  { key: "account", tools: ["get_credit_balance"] },
] as const;

export default async function HomePage() {
  const t = await getTranslations("public");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <JsonLd data={ORGANIZATION_SCHEMA} />
      <JsonLd data={WEBSITE_SCHEMA} />

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden border-b border-border">
        <div className="hero-glow pointer-events-none absolute inset-0" aria-hidden />
        <div
          className="bg-grain pointer-events-none absolute inset-0 opacity-[0.05] mix-blend-multiply dark:opacity-[0.08] dark:mix-blend-screen"
          aria-hidden
        />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-6 py-20 md:py-24 lg:grid-cols-2 lg:gap-10">
          <div className="text-center lg:text-left">
            <Badge
              variant="outline"
              className="mb-6 gap-2 bg-background/60 px-4 py-1 text-sm font-normal backdrop-blur"
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
              </span>
              {t("hero.badge")}
            </Badge>
            <h1 className="mb-6 font-serif text-5xl leading-[1.05] text-foreground md:text-6xl xl:text-7xl">
              {t("hero.titleLine1")}
              <br />
              {t("hero.titleLine2")}
              <br />
              <span className="text-primary">{t("hero.titleLine3")}</span>
            </h1>
            <p className="mx-auto mb-3 max-w-xl text-lg text-muted-foreground lg:mx-0">
              {t("hero.subtitle")}
            </p>
            <p className="mb-8 text-sm italic text-muted-foreground">
              {t("hero.tagline")}
            </p>
            <div className="flex flex-col justify-center gap-3 sm:flex-row lg:justify-start">
              <Link href="/signup">
                <Button size="lg" className="w-full gap-2 px-8 shadow-warm-sm sm:w-auto">
                  {t("hero.getStartedFree")}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
              <Link href="/marketplace">
                <Button
                  size="lg"
                  variant="outline"
                  className="w-full gap-2 px-8 sm:w-auto"
                >
                  {t("hero.browseTemplates")}
                </Button>
              </Link>
            </div>
          </div>

          <Reveal delay={120}>
            <ProductFrame
              lightSrc="/home/builder-light.png"
              darkSrc="/home/builder-dark.png"
              alt={t("hero.heroVisualAlt")}
              width={2504}
              height={1724}
              label={t("hero.visualBuilderLabel")}
              priority
              className="lg:-rotate-1"
            />
          </Reveal>
        </div>
      </section>

      {/* ── Credibility strip ──────────────────────────────────────────── */}
      <StatStrip
        items={[
          { icon: Cpu, label: t("hero.openSourceSolver") },
          { icon: LayoutTemplate, label: t("hero.templatesCount") },
          { icon: Store, label: t("hero.firstMarketplace") },
          { icon: Bot, label: t("hero.mcpNative") },
        ]}
        github={{ label: t("hero.viewSource"), href: GITHUB_REPO_URL }}
      />

      {/* ── Platform (bento) ───────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <SectionHeading
            eyebrow={t("platform.eyebrow")}
            title={t("platform.title")}
            subtitle={t("platform.subtitle")}
          />
        </Reveal>
        <div className="mt-14 grid gap-6 lg:grid-cols-2">
          {/* Featured cell — AI Builder, spans both rows on the left */}
          <Reveal className="lg:row-span-2">
            <Card className="h-full border-border shadow-warm-sm transition-shadow duration-300 hover:shadow-warm-md">
              <CardContent className="flex h-full flex-col p-8">
                <div
                  className="mb-6 flex h-14 w-14 items-center justify-center rounded-md"
                  style={chipStyle(HERO_PILLARS[0].accent)}
                >
                  <Sparkles className="h-7 w-7" />
                </div>
                <h3 className="mb-3 font-serif text-2xl">
                  {t(`hero.pillars.${HERO_PILLARS[0].key}.title`)}
                </h3>
                <p className="mb-6 max-w-md text-muted-foreground">
                  {t(`hero.pillars.${HERO_PILLARS[0].key}.description`)}
                </p>
                <ProductFrame
                  lightSrc="/home/ai-assistant-light.png"
                  darkSrc="/home/ai-assistant-dark.png"
                  alt={t("platform.aiVisualAlt")}
                  width={2880}
                  height={1800}
                  label={t("hero.pillars.aiBuilder.title")}
                  className="mb-8"
                />
                <div className="mt-auto">
                  <Link href={HERO_PILLARS[0].cta.href}>
                    <Button variant="outline" className="gap-1.5">
                      {t(HERO_PILLARS[0].cta.key)}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          </Reveal>

          {HERO_PILLARS.slice(1).map((pillar, idx) => (
            <Reveal key={pillar.key} delay={(idx + 1) * 90}>
              <Card className="h-full border-border shadow-warm-sm transition-shadow duration-300 hover:shadow-warm-md">
                <CardContent className="p-8">
                  <div
                    className="mb-4 flex h-11 w-11 items-center justify-center rounded-md"
                    style={chipStyle(pillar.accent)}
                  >
                    <pillar.icon className="h-5 w-5" />
                  </div>
                  <h3 className="mb-2 font-serif text-xl">
                    {t(`hero.pillars.${pillar.key}.title`)}
                  </h3>
                  <p className="mb-4 text-sm text-muted-foreground">
                    {t(`hero.pillars.${pillar.key}.description`)}
                  </p>
                  <Link href={pillar.cta.href}>
                    <Button variant="outline" size="sm" className="gap-1.5">
                      {t(pillar.cta.key)}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </Link>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── Audience ───────────────────────────────────────────────────── */}
      <section className="border-y border-border bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <SectionHeading title={t("audience.title")} />
          </Reveal>
          <div className="mt-14 grid grid-cols-1 gap-8 md:grid-cols-3">
            {AUDIENCE.map((aud, idx) => (
              <Reveal key={aud.key} delay={idx * 90}>
                <Card className="relative h-full overflow-hidden border-border shadow-warm-sm transition-shadow duration-300 hover:shadow-warm-md">
                  <span
                    className="absolute inset-x-0 top-0 h-1"
                    style={{ backgroundColor: `var(${aud.accent})` }}
                    aria-hidden
                  />
                  <CardContent className="flex h-full flex-col p-8">
                    <div
                      className="mb-6 flex h-12 w-12 items-center justify-center rounded-md"
                      style={chipStyle(aud.accent)}
                    >
                      <aud.icon className="h-6 w-6" />
                    </div>
                    <h3 className="mb-4 font-serif text-xl">
                      {t(`audience.${aud.key}.title`)}
                    </h3>
                    <ul className="mb-6 space-y-3 text-sm text-muted-foreground">
                      {AUDIENCE_ITEMS.map((item) => (
                        <li key={item} className="flex items-start gap-2">
                          <Check
                            className="mt-0.5 h-4 w-4 shrink-0"
                            style={{ color: `var(${aud.accent})` }}
                          />
                          {t(`audience.${aud.key}.${item}`)}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-auto">
                      <Link href={aud.href}>
                        <Button variant="outline" size="sm">
                          {t(`audience.${aud.key}.cta`)}
                        </Button>
                      </Link>
                    </div>
                  </CardContent>
                </Card>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── Use cases ──────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <SectionHeading
            title={t("useCases.title")}
            subtitle={t("useCases.subtitle")}
          />
        </Reveal>
        <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {USE_CASE_KEYS.map((uc, idx) => {
            const accent = uc.source === "ai" ? ACCENT_TERRACOTTA : ACCENT_SAGE;
            return (
              <Reveal key={uc.key} delay={(idx % 3) * 80}>
                <Card className="h-full overflow-hidden border-border shadow-warm-sm transition-shadow duration-300 hover:shadow-warm-md">
                  <CardContent className="flex h-full flex-col p-6">
                    <div
                      className="mb-4 flex h-10 w-10 items-center justify-center rounded-md"
                      style={chipStyle(accent)}
                    >
                      <uc.icon className="h-5 w-5" />
                    </div>
                    <h3 className="mb-2 font-serif text-lg">
                      {t(`useCases.${uc.key}.title`)}
                    </h3>
                    <p className="mb-4 text-sm text-muted-foreground">
                      {t(`useCases.${uc.key}.scenario`)}
                    </p>
                    <div className="mt-auto">
                      <div className="mb-4 flex flex-wrap items-center gap-2">
                        <span
                          className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                          style={chipStyle(accent)}
                        >
                          {t(`useCases.${uc.key}.result`)}
                        </span>
                        <Badge
                          variant="secondary"
                          className="shrink-0 gap-1 text-xs font-normal"
                        >
                          {uc.source === "ai" ? (
                            <>
                              <Sparkles className="h-3 w-3" />
                              {t("useCases.builtWithAi")}
                            </>
                          ) : (
                            <>
                              <Store className="h-3 w-3" />
                              {t("useCases.fromMarketplace")}
                            </>
                          )}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-3">
                        <Link href="/marketplace">
                          <Button variant="outline" size="sm" className="text-xs">
                            {t("useCases.tryTemplate")}
                          </Button>
                        </Link>
                        <Link
                          href="/signup"
                          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                        >
                          {t("useCases.getStarted")}
                        </Link>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* ── MCP showcase ───────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <SectionHeading title={t("mcp.title")} subtitle={t("mcp.subtitle")} />
        </Reveal>
        <div className="mt-14 grid grid-cols-1 gap-12 lg:grid-cols-2">
          <div className="space-y-6">
            {(["discover", "authenticate", "solve", "results"] as const).map(
              (step, idx) => (
                <Reveal key={step} delay={idx * 70}>
                  <div className="flex gap-4">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                      {idx + 1}
                    </div>
                    <div>
                      <h3 className="mb-1 font-semibold">
                        {t(`mcp.workflow.${step}.title`)}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {t(`mcp.workflow.${step}.description`)}
                      </p>
                    </div>
                  </div>
                </Reveal>
              ),
            )}
          </div>

          <Reveal delay={120}>
            <Card className="overflow-hidden border-border shadow-warm-md">
              <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-4 py-2.5">
                <span className="h-2.5 w-2.5 rounded-full bg-[#E8A088]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#8AA499]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#9B8E88]" />
                <span className="ml-3 font-mono text-xs text-muted-foreground">
                  {t("mcp.toolsTitle")}
                </span>
              </div>
              <CardContent className="space-y-4 p-6">
                {MCP_TOOL_GROUPS.map((group) => (
                  <div key={group.key}>
                    <p className="mb-1 text-sm font-medium text-foreground">
                      {t(`mcp.tools.${group.key}`)}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {group.tools.map((tool) => (
                        <Badge
                          key={tool}
                          variant="secondary"
                          className="font-mono text-xs font-normal"
                        >
                          {tool}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </Reveal>
        </div>

        <div className="mt-12 text-center">
          <Badge variant="outline" className="mb-6 px-4 py-1.5 text-sm font-normal">
            {t("mcp.agentBadge")}
          </Badge>
          <div className="mt-4">
            <Link href="/docs/mcp/overview">
              <Button variant="outline" size="lg" className="gap-2">
                <Bot className="h-4 w-4" />
                {t("mcp.cta")}
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <section className="border-y border-border bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <SectionHeading title={t("howItWorks.title")} />
          </Reveal>
          <div className="relative mt-14 grid grid-cols-1 gap-8 md:grid-cols-3">
            {/* Connecting hairline behind the numbered steps (desktop only) */}
            <div
              className="absolute left-[16.66%] right-[16.66%] top-5 hidden h-px bg-border md:block"
              aria-hidden
            />
            {HOW_IT_WORKS_KEYS.map((stepKey, idx) => (
              <Reveal key={stepKey} delay={idx * 90}>
                <div className="relative text-center">
                  <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground shadow-warm-sm">
                    {idx + 1}
                  </div>
                  <h3 className="mb-2 font-semibold">
                    {t(`howItWorks.${stepKey}.title`)}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    {t(`howItWorks.${stepKey}.description`)}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ──────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden py-28 text-center">
        <div className="cta-band pointer-events-none absolute inset-0" aria-hidden />
        <div
          className="bg-grain pointer-events-none absolute inset-0 opacity-[0.05] mix-blend-multiply dark:opacity-[0.08] dark:mix-blend-screen"
          aria-hidden
        />
        <div className="relative mx-auto max-w-2xl px-6">
          <h2 className="mb-4 font-serif text-4xl leading-tight md:text-5xl">
            {t("cta.title")}
          </h2>
          <p className="mx-auto mb-8 max-w-md text-muted-foreground">
            {t("cta.subtitle")}
          </p>
          <Link href="/signup">
            <Button size="lg" className="gap-2 px-10 shadow-warm-md">
              {t("cta.button")}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>
    </div>
  );
}

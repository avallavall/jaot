import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Reveal } from "@/components/motion/Reveal";
import { BottleneckShowcase } from "@/components/landing/BottleneckShowcase";
import { CatalogIndex } from "@/components/landing/CatalogIndex";
import { ConflictShowcase } from "@/components/landing/ConflictShowcase";
import { JModelShowcase } from "@/components/landing/JModelShowcase";
import { ProductFrame } from "@/components/landing/ProductFrame";
import { ProvenOptimalHero } from "@/components/landing/ProvenOptimalHero";
import { SectionHeading } from "@/components/landing/SectionHeading";
import { StatStrip } from "@/components/landing/StatStrip";
import { cn } from "@/lib/utils";
import { GITHUB_REPO_URL } from "@/lib/community";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildOrganizationSchema, buildWebSiteSchema } from "@/lib/seo/schemas";
import { BASE_URL } from "@/lib/seo/urls";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Building2,
  Calendar,
  Check,
  Cpu,
  Factory,
  Gauge,
  GraduationCap,
  LayoutTemplate,
  Network,
  PieChart,
  Sparkles,
  Store,
  TrendingUp,
  Truck,
  Users,
  Wrench,
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

// What each way in actually looks like. The prompt is a sentence a person types,
// so it is translated; the other two are identifiers — a real template from
// app/data/templates/agriculture.yaml and a real MCP tool — so they render as
// authored, the same call made for the tool listing further down.
const ENTRY_SAMPLES: Record<string, (t: (key: string) => string) => string> = {
  aiBuilder: (t) => t("platform.samplePrompt"),
  marketplace: () => "Fertilizer Mix Optimizer — agriculture",
  mcp: () => 'solve_with_template(template_id="fertilizer_mixing")',
};

const AUDIENCE = [
  { icon: Building2, key: "teams", href: "/signup", accent: ACCENT_SEPIA },
  { icon: Store, key: "authors", href: "/marketplace", accent: ACCENT_TERRACOTTA },
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

// The exact-analysis card was dropped: BottleneckShowcase demonstrates it on a
// real solve rather than describing it. These three are capabilities the panel
// cannot show by itself.
const SOLUTION_EXPLAINER_KEYS = [
  { icon: Network, key: "structuredSolution" },
  { icon: Sparkles, key: "aiExplain" },
] as const;

const INFEASIBILITY_KEYS = [
  { icon: AlertTriangle, key: "conflict" },
  { icon: Wrench, key: "fix" },
  { icon: Gauge, key: "honest" },
] as const;

const HOW_IT_WORKS_KEYS = ["step1", "step2", "step3"] as const;

// Mirrors the real MCP surface (app/mcp include_operations, 30 tools) — keep in
// sync when tools are added/retired; llms.txt and docs/mcp/overview are the
// other two copies.
const MCP_TOOL_GROUPS = [
  {
    key: "problemSolving",
    tools: ["solve_problem", "validate_problem", "solve_multi_objective", "list_available_solvers"],
  },
  {
    key: "templates",
    tools: ["list_templates", "get_template", "solve_with_template"],
  },
  {
    key: "fileIO",
    tools: ["import_preview", "import_and_solve", "export_model", "export_execution"],
  },
  {
    key: "marketplace",
    tools: ["list_catalog_models", "get_catalog_model", "get_catalog_model_schema"],
  },
  {
    key: "modelProjects",
    tools: [
      "create_model_project",
      "create_model_project_from_marketplace",
      "update_model_project_draft",
      "commit_model_version",
      "list_project_versions",
      "get_model_stats",
      "solve_model_project",
      "get_model_project",
      "list_model_projects",
    ],
  },
  { key: "execution", tools: ["execute_model", "get_execution", "get_execution_insights"] },
  {
    key: "analysis",
    tools: [
      "get_execution_exact_analysis",
      "analyze_infeasibility",
      "start_execution_scenario_analysis",
      "get_execution_scenario_analysis",
    ],
  },
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
            {/* Each line is its own block so the three-beat rhythm survives, and
                text-balance evens the wrap inside a line. No hyphens-auto here:
                it broke English mid-word ("bud-gets"). German compounds are the
                reason break-words stays — "Optimierungslösungen" has nowhere to
                wrap — but the type scale is now small enough not to need it. */}
            <h1 className="mb-6 font-serif text-4xl leading-[1.08] text-balance text-foreground md:text-5xl xl:text-6xl">
              <span className="block break-words">{t("hero.titleLine1")}</span>
              <span className="block break-words">{t("hero.titleLine2")}</span>
              <span className="block break-words text-primary">{t("hero.titleLine3")}</span>
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

          {/* The hero visual is a real solve, replayed from a trace SCIP produced
              (scripts/gen_hero_trace.py) — not a screenshot that goes stale. It
              replaced a capture of the retired visual builder, which the front
              page was still selling as a way in. */}
          <ProvenOptimalHero />
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
        {/* Each way in is shown by the gesture it actually takes — a sentence you
            type, a template you pick, a tool an agent calls — instead of three
            cards asserting the door exists. The three samples deliberately share
            one thread: the same real template, reached three different ways. */}
        <div className="mt-14 grid gap-10 md:grid-cols-3 md:gap-0">
          {HERO_PILLARS.map((pillar, idx) => (
            <Reveal key={pillar.key} delay={idx * 90}>
              <div
                className={cn(
                  "flex h-full flex-col md:px-8",
                  idx === 0 && "md:pl-0",
                  idx > 0 && "md:border-l md:border-border",
                  idx === HERO_PILLARS.length - 1 && "md:pr-0",
                )}
              >
                <h3 className="mb-2.5 flex items-center gap-2.5 font-serif text-xl">
                  <pillar.icon
                    className="h-5 w-5 shrink-0"
                    style={{ color: `var(${pillar.accent})` }}
                    aria-hidden
                  />
                  {t(`hero.pillars.${pillar.key}.title`)}
                </h3>
                <p className="mb-5 text-sm leading-relaxed text-muted-foreground">
                  {t(`hero.pillars.${pillar.key}.description`)}
                </p>

                <div className="mb-5 border-l-2 border-border py-1 pl-4">
                  <p className="font-mono text-xs leading-relaxed text-foreground">
                    {ENTRY_SAMPLES[pillar.key](t)}
                  </p>
                </div>

                <div className="mt-auto">
                  <Link
                    href={pillar.cta.href}
                    className="font-mono text-xs uppercase tracking-widest text-primary underline-offset-4 hover:underline"
                  >
                    {t(pillar.cta.key)}
                  </Link>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        {/* The AI builder is the front door, and a line of sample prompt did not
            carry it. This capture is a screen that genuinely exists, so it keeps
            the window chrome — unlike the hero, which is the solver running. */}
        <Reveal delay={200}>
          <div className="mx-auto mt-14 max-w-4xl">
            <ProductFrame
              lightSrc="/home/ai-assistant-light.png"
              darkSrc="/home/ai-assistant-dark.png"
              alt={t("platform.aiVisualAlt")}
              width={2880}
              height={1800}
              label={t("hero.pillars.aiBuilder.title")}
            />
          </div>
        </Reveal>
      </section>

      {/* ── JModel ─────────────────────────────────────────────────────────
          The biggest gap in the page: JModel is the product (the JAOT_DSL flag
          was retired for that reason) and the home never mentioned it. Source and
          real compiler notation, side by side, same renderer as the studio. */}
      <section className="border-y border-border bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <SectionHeading
              eyebrow={t("jmodel.eyebrow")}
              title={t("jmodel.title")}
              subtitle={t("jmodel.subtitle")}
            />
          </Reveal>
          <Reveal delay={120}>
            <div className="mt-14">
              <JModelShowcase />
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Understand your solution ───────────────────────────────────────
          A solved instance whose answer contradicts the obvious one, instead of
          four cards describing that analysis exists. The three capabilities that
          the panel does not itself demonstrate stay below it as a compact strip. */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <SectionHeading
            eyebrow={t("exactAnalysis.eyebrow")}
            title={t("exactAnalysis.title")}
            subtitle={t("exactAnalysis.subtitle")}
          />
        </Reveal>

        <Reveal delay={120}>
          <div className="mt-14">
            <BottleneckShowcase />
          </div>
        </Reveal>

        {/* "What if" leads on its own: re-solving the perturbed MIP instead of
            reading a number off a relaxation is the sharpest technical claim on
            this page, and compressing it into a third of a row buried it. */}
        <Reveal delay={160}>
          <div className="mt-12 grid gap-8 border-t border-border pt-8 lg:grid-cols-[1fr_1.6fr] lg:gap-12">
            <h3 className="flex items-start gap-3 font-serif text-2xl leading-snug">
              <TrendingUp className="mt-1.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
              {t("solutionExplainer.whatIf.title")}
            </h3>
            <p className="text-base leading-relaxed text-muted-foreground">
              {t("solutionExplainer.whatIf.description")}
            </p>
          </div>
        </Reveal>

        <div className="mt-10 grid gap-8 sm:grid-cols-2">
          {SOLUTION_EXPLAINER_KEYS.map((item, idx) => (
            <Reveal key={item.key} delay={(idx + 1) * 80}>
              <div className="border-t border-border pt-4">
                <h3 className="mb-1.5 flex items-center gap-2 font-serif text-base">
                  <item.icon className="h-4 w-4 text-primary" aria-hidden />
                  {t(`solutionExplainer.${item.key}.title`)}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t(`solutionExplainer.${item.key}.description`)}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── Infeasibility explainer ────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <SectionHeading
            eyebrow={t("conflict.eyebrow")}
            title={t("conflict.title")}
            subtitle={t("conflict.subtitle")}
          />
        </Reveal>

        <Reveal delay={120}>
          <div className="mt-14">
            <ConflictShowcase />
          </div>
        </Reveal>

        <div className="mt-12 grid gap-8 sm:grid-cols-3">
          {INFEASIBILITY_KEYS.map((item, idx) => (
            <Reveal key={item.key} delay={(idx + 1) * 80}>
              <div className="border-t border-border pt-4">
                <h3 className="mb-1.5 flex items-center gap-2 font-serif text-base">
                  <item.icon className="h-4 w-4 text-primary" aria-hidden />
                  {t(`infeasibilityHighlight.${item.key}.title`)}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t(`infeasibilityHighlight.${item.key}.description`)}
                </p>
              </div>
            </Reveal>
          ))}
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
              {/* An API index rather than a pile of pills: the tool names are the
                  real ones an agent calls, so they read better as a listing. The
                  count is computed, so it cannot drift from the array. */}
              <CardContent className="p-6">
                {/* Two columns: thirty names in one stack towered over the four
                    steps beside it and left the section lopsided. */}
                <div className="gap-x-6 sm:columns-2">
                  {MCP_TOOL_GROUPS.map((group) => (
                    <div key={group.key} className="mb-5 break-inside-avoid">
                      <p className="mb-1.5 font-mono text-[0.625rem] uppercase tracking-widest text-muted-foreground">
                        {t(`mcp.tools.${group.key}`)}
                      </p>
                      <ul className="space-y-0.5">
                        {group.tools.map((tool) => (
                          <li key={tool} className="font-mono text-xs text-foreground">
                            {tool}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <p className="border-t border-border pt-4 font-mono text-xs text-muted-foreground">
                  {t("mcp.toolCount", {
                    count: MCP_TOOL_GROUPS.reduce((n, g) => n + g.tools.length, 0),
                  })}
                </p>
              </CardContent>
            </Card>
          </Reveal>
        </div>

        <div className="mt-12 text-center">
          {/* The Badge primitive is whitespace-nowrap, which is right for a status
              pill and wrong for a sentence: at 390px this one measured 403px and
              pushed the page into horizontal scroll. Let it wrap here. */}
          <Badge
            variant="outline"
            className="mb-6 max-w-full whitespace-normal text-balance px-4 py-1.5 text-sm font-normal"
          >
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

      {/* ── Audience ───────────────────────────────────────────────────── */}
      <section className="border-y border-border bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <SectionHeading title={t("audience.title")} />
          </Reveal>
          {/* Three columns divided by a rule, not three cards. The accent survives
              as the heading's marker so the audiences stay distinguishable. */}
          <div className="mt-14 grid grid-cols-1 gap-10 md:grid-cols-3 md:gap-0">
            {AUDIENCE.map((aud, idx) => (
              <Reveal key={aud.key} delay={idx * 90}>
                <div
                  className={cn(
                    "flex h-full flex-col md:px-8",
                    idx === 0 && "md:pl-0",
                    idx > 0 && "md:border-l md:border-border",
                    idx === AUDIENCE.length - 1 && "md:pr-0",
                  )}
                >
                  <h3 className="mb-5 flex items-center gap-2.5 font-serif text-xl">
                    <aud.icon
                      className="h-5 w-5 shrink-0"
                      style={{ color: `var(${aud.accent})` }}
                      aria-hidden
                    />
                    {t(`audience.${aud.key}.title`)}
                  </h3>
                  <ul className="mb-6 space-y-2.5 text-sm leading-relaxed text-muted-foreground">
                    {AUDIENCE_ITEMS.map((item) => (
                      <li key={item} className="flex items-start gap-2">
                        <Check
                          className="mt-1 h-3.5 w-3.5 shrink-0"
                          style={{ color: `var(${aud.accent})` }}
                          aria-hidden
                        />
                        {t(`audience.${aud.key}.${item}`)}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-auto">
                    <Link
                      href={aud.href}
                      className="font-mono text-xs uppercase tracking-widest text-primary underline-offset-4 hover:underline"
                    >
                      {t(`audience.${aud.key}.cta`)}
                    </Link>
                  </div>
                </div>
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
        {/* The real catalogue, counted from the YAML it ships from, instead of six
            hand-picked cards that drift the moment a template is added. */}
        <Reveal delay={100}>
          <div className="mt-14">
            <CatalogIndex />
          </div>
        </Reveal>

        {/* The worked examples stay, compressed: they name concrete problems in
            words a visitor recognises, which the sector index alone does not. */}
        <div className="mt-14 grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          {USE_CASE_KEYS.map((uc, idx) => (
            <Reveal key={uc.key} delay={(idx % 3) * 70}>
              <div className="border-t border-border pt-4">
                <h3 className="mb-1.5 flex items-center gap-2 font-serif text-base">
                  <uc.icon
                    className="h-4 w-4"
                    style={{
                      color: `var(${uc.source === "ai" ? ACCENT_TERRACOTTA : ACCENT_SAGE})`,
                    }}
                    aria-hidden
                  />
                  {t(`useCases.${uc.key}.title`)}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t(`useCases.${uc.key}.scenario`)}
                </p>
                <p className="mt-1.5 font-mono text-xs text-muted-foreground">
                  {uc.source === "ai" ? t("useCases.builtWithAi") : t("useCases.fromMarketplace")}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <section className="border-y border-border bg-muted/30 py-24">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <SectionHeading title={t("howItWorks.title")} />
          </Reveal>
          {/* The numeral carries the sequence typographically — no pills, no
              connector line pretending to be a diagram. */}
          <div className="mt-14 grid grid-cols-1 gap-10 md:grid-cols-3">
            {HOW_IT_WORKS_KEYS.map((stepKey, idx) => (
              <Reveal key={stepKey} delay={idx * 90}>
                <div className="flex gap-5">
                  <span
                    className="font-serif text-5xl leading-none text-primary/25 tabular-nums"
                    aria-hidden
                  >
                    {idx + 1}
                  </span>
                  <div className="pt-1">
                    <h3 className="mb-1.5 font-serif text-lg">
                      {t(`howItWorks.${stepKey}.title`)}
                    </h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {t(`howItWorks.${stepKey}.description`)}
                    </p>
                  </div>
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

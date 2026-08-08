import { getFormatter, getTranslations } from "next-intl/server";
import { cn } from "@/lib/utils";
import { ANALYSIS_SHOWCASE } from "./data/analysisShowcase";

/**
 * What JAOT tells you after a solve, on a real solved instance.
 *
 * The instance (scripts/gen_landing_analysis.py) is a power-electronics plant's
 * quarterly build plan, chosen because its answer contradicts the obvious one
 * twice over: the three highest-margin families are not built at all, and the
 * component everyone assumes is the bottleneck finishes the quarter with nearly
 * half of it unused. That is the case for owning an optimizer, and it is far
 * more convincing than an adjective.
 *
 * The figures are the exact analysis — utilisation from b − a·x*, contributions
 * from c·x* — not LP shadow prices, matching what the product actually computes
 * (app/domains/solver/services/exact_analysis.py).
 *
 * No client JavaScript: it is a Server Component and the bars are plain CSS
 * widths, so this section costs nothing at load.
 */
export async function BottleneckShowcase() {
  const t = await getTranslations("public.exactAnalysis");
  const format = await getFormatter();
  const { objective, constraints, contributions, loosest, meta } = ANALYSIS_SHOWCASE;

  const money = (value: number) =>
    format.number(value, { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

  const topMargin = contributions[0];
  const maxContribution = Math.max(...contributions.map((c) => c.contribution), 1);
  const capacityRows = constraints.filter((c) => c.operator === "<=");
  const floorRows = constraints.filter((c) => c.operator === ">=");

  return (
    <div className="grid gap-px overflow-hidden border border-border bg-border md:grid-cols-2">
      {/* Left: the plan. Ordered by margin per unit, which is deliberately NOT
          the order the solver chose — the top three rows sit at zero. */}
      <div className="bg-card p-6 sm:p-8">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h3 className="font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
            {t("planHeading")}
          </h3>
          <span className="font-mono text-[0.6875rem] text-muted-foreground">
            {t("planMeta", { units: format.number(meta.unitsBuilt), solver: meta.solver })}
          </span>
        </div>

        <ul className="mt-6 space-y-4">
          {contributions.map((item) => {
            const inPlan = item.units > 0;
            return (
              <li key={item.key}>
                <div className="flex items-baseline justify-between gap-4">
                  <span
                    className={cn(
                      "font-serif text-lg",
                      inPlan ? "text-foreground" : "text-muted-foreground line-through decoration-1",
                    )}
                  >
                    {t(`products.${item.key}`)}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {t("perUnit", { margin: money(item.margin) })}
                  </span>
                </div>

                <div className="mt-1.5 flex items-center gap-3">
                  <div className="h-1.5 flex-1 bg-muted">
                    <div
                      className={cn("h-full", inPlan ? "bg-primary" : "bg-transparent")}
                      style={{ width: `${(item.contribution / maxContribution) * 100}%` }}
                    />
                  </div>
                  <span
                    className={cn(
                      "w-24 shrink-0 text-right font-mono text-xs tabular-nums",
                      inPlan ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {t("units", { count: format.number(item.units) })}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="mt-6 flex items-baseline justify-between border-t border-border pt-4">
          <span className="font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
            {t("totalMargin")}
          </span>
          <span className="font-mono text-lg tabular-nums text-primary">{money(objective)}</span>
        </div>
      </div>

      {/* Right: why. Three limits run out; the one everybody blames does not. */}
      <div className="bg-card p-6 sm:p-8">
        <h3 className="font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
          {t("bindingHeading")}
        </h3>

        {/* Only capacity limits get a utilisation bar. A ">=" row is a floor, not
            something that runs out — drawing it at 40% of "capacity" would read
            as underused when it is a minimum comfortably cleared. */}
        <ul className="mt-6 space-y-5">
          {capacityRows.map((row) => (
            <li key={row.key}>
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-foreground">{t(`resources.${row.key}`)}</span>
                <span
                  className={cn(
                    "font-mono text-xs tabular-nums",
                    row.binding ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {row.binding
                    ? t("binding")
                    : t("slack", { slack: format.number(row.slack) })}
                </span>
              </div>
              <div className="mt-1.5 h-1.5 bg-muted">
                <div
                  className={cn("h-full", row.binding ? "bg-primary" : "bg-accent")}
                  style={{ width: `${Math.min(row.utilization, 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>

        {floorRows.length > 0 ? (
          <ul className="mt-5 space-y-1.5 border-t border-border pt-4">
            {floorRows.map((row) => (
              <li key={row.key} className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-muted-foreground">{t(`resources.${row.key}`)}</span>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {t("floorMet", {
                    required: format.number(row.capacity),
                    actual: format.number(row.activity),
                  })}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        <p className="mt-6 border-t border-border pt-4 text-sm leading-relaxed text-muted-foreground">
          {t("verdict", {
            product: t(`products.${topMargin.key}`),
            margin: money(topMargin.margin),
            binding: meta.bindingCount,
            spare: format.number(loosest.slack),
            spareResource: t(`resourcesInline.${loosest.key}`),
          })}
        </p>
      </div>
    </div>
  );
}

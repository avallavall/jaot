import { getFormatter, getTranslations } from "next-intl/server";
import { cn } from "@/lib/utils";
import { INFEASIBLE_SHOWCASE } from "./data/infeasibleShowcase";

/**
 * What JAOT says when the model has no answer, on a genuinely infeasible run.
 *
 * A solver returns "infeasible" and stops, which leaves you to audit the whole
 * model. JAOT reduces it to an irreducible infeasible set by deletion filtering
 * — one feasibility re-solve per rule — so it can name the rules that clash AND
 * clear the ones that do not. The instance here (scripts/gen_landing_infeasible.py)
 * is a quarter's worth of traction inverters the plant cannot carry: seven rules,
 * and exactly two of them are the problem.
 *
 * Ceilings are drawn as bars in units of the product; the contract is the line
 * they have to reach, because a ">=" demand is not a ceiling and drawing it as
 * one would misrepresent it.
 *
 * Server Component: no client JavaScript.
 */
export async function ConflictShowcase() {
  const t = await getTranslations("public.conflict");
  const format = await getFormatter();
  const { demand, rules, shortfall, meta } = INFEASIBLE_SHOWCASE;
  const num = (value: number) => format.number(value);

  const ceilings = rules.filter((r) => r.operator === "<=");
  const scale = Math.max(...ceilings.map((r) => r.allows), demand) * 1.08;
  const demandAt = (demand / scale) * 100;
  // The caption hangs off the contract line. Past the middle of the track it has
  // to hang the other way, or on a narrow viewport it runs out of the card and
  // takes the whole page into horizontal scroll with it.
  const captionTrails = demandAt > 55;

  return (
    <div className="border border-border bg-card p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h3 className="font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
          {t("chartHeading")}
        </h3>
        <span className="font-mono text-[0.6875rem] text-muted-foreground">
          {t("method", { rules: meta.totalRules, size: meta.conflictSize })}
        </span>
      </div>

      <div className="relative mt-8">
        {/* The contract line: what every ceiling has to clear. */}
        <div
          className="pointer-events-none absolute bottom-0 top-0 border-l border-dashed border-primary/50"
          style={{ left: `${demandAt}%` }}
          aria-hidden
        />

        <ul className="space-y-6">
          {ceilings.map((rule) => {
            const width = (rule.allows / scale) * 100;
            const short = rule.allows < demand;
            return (
              <li key={rule.key}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <span
                    className={cn(
                      "text-sm",
                      rule.inConflict ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {t(`rules.${rule.key}`)}{" "}
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {t("reaches", { units: num(rule.allows) })}
                    </span>
                  </span>
                  <span
                    className={cn(
                      "font-mono text-xs tabular-nums",
                      rule.inConflict ? "text-primary" : "text-muted-foreground",
                    )}
                  >
                    {rule.inConflict ? t("inConflict") : t("cleared")}
                  </span>
                </div>

                {/* The track spans the full width of the same box the contract
                    line is positioned in — otherwise the two use different
                    coordinate systems and a limit that reaches the demand
                    exactly appears to fall short of the line. */}
                <div className="mt-2 h-2 w-full bg-muted">
                  <div
                    className={cn(
                      "h-full",
                      short ? "bg-primary" : "bg-accent",
                      rule.inConflict ? "opacity-100" : "opacity-45",
                    )}
                    style={{ width: `${Math.min(width, 100)}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>

        <div className="relative mt-3 h-4">
          <span
            className={cn(
              "absolute whitespace-nowrap font-mono text-[0.6875rem] text-primary",
              captionTrails ? "pr-2 text-right" : "pl-2",
            )}
            style={
              captionTrails ? { right: `${100 - demandAt}%` } : { left: `${demandAt}%` }
            }
          >
            {t("contractLine", { demand: num(demand) })}
          </span>
        </div>
      </div>

      <p className="mt-8 border-t border-border pt-5 text-sm leading-relaxed text-muted-foreground">
        {t("verdict", {
          resource: t(`rulesInline.${shortfall.resource}`),
          reaches: num(shortfall.reaches),
          demand: num(demand),
          missing: num(shortfall.missing),
          cleared: meta.clearedCount,
        })}
      </p>
    </div>
  );
}

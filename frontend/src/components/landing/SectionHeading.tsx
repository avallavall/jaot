import { cn } from "@/lib/utils";

interface SectionHeadingProps {
  /** Small uppercase kicker above the title. */
  eyebrow?: string;
  title: string;
  subtitle?: string;
  align?: "center" | "left";
  className?: string;
}

/**
 * Editorial section heading: an accented eyebrow + a serif (Fraunces) title +
 * optional muted subtitle. Replaces the repeated bare `<h2 font-serif>` blocks
 * so every section shares one rhythm.
 */
export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = "center",
  className,
}: SectionHeadingProps) {
  const centered = align === "center";

  return (
    <div
      className={cn(
        "max-w-2xl",
        centered ? "mx-auto text-center" : "text-left",
        className,
      )}
    >
      {eyebrow ? (
        <div
          className={cn(
            "mb-4 flex items-center gap-2",
            centered && "justify-center",
          )}
        >
          <span className="h-px w-6 bg-accent" />
          <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {eyebrow}
          </span>
          <span className="h-px w-6 bg-accent" />
        </div>
      ) : null}
      <h2 className="font-serif text-3xl leading-tight text-foreground md:text-4xl">
        {title}
      </h2>
      {subtitle ? (
        <p className="mt-4 text-muted-foreground">{subtitle}</p>
      ) : null}
    </div>
  );
}

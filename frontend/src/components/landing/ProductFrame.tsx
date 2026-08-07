import Image from "next/image";
import { cn } from "@/lib/utils";

interface ProductFrameProps {
  lightSrc: string;
  darkSrc: string;
  alt: string;
  /** Intrinsic capture dimensions (the image scales responsively). */
  width: number;
  height: number;
  /** Optional monospace label shown in the faux window titlebar. */
  label?: string;
  className?: string;
  priority?: boolean;
}

/**
 * Frames a real product screenshot as a squared "app window" — faux titlebar
 * with vintage traffic-light dots + warm layered shadow — so the node editor
 * reads as the product without breaking the squared, paper aesthetic.
 *
 * Renders both light and dark captures and swaps via the `.dark` class. The
 * dark image is lazy (no layout box while hidden) so only the active theme's
 * asset is fetched; the light image is eager (default theme, above the fold).
 */
export function ProductFrame({
  lightSrc,
  darkSrc,
  alt,
  width,
  height,
  label,
  className,
  priority = false,
}: ProductFrameProps) {
  return (
    <div
      className={cn(
        "overflow-hidden border border-border bg-card shadow-warm-lg",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#E8A088]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#8AA499]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#9B8E88]" />
        {label ? (
          <span className="ml-3 truncate font-mono text-xs text-muted-foreground">
            {label}
          </span>
        ) : null}
      </div>
      <Image
        src={lightSrc}
        alt={alt}
        width={width}
        height={height}
        priority={priority}
        sizes="(min-width: 1024px) 50vw, 100vw"
        className="block h-auto w-full dark:hidden"
      />
      <Image
        src={darkSrc}
        alt=""
        aria-hidden
        width={width}
        height={height}
        sizes="(min-width: 1024px) 50vw, 100vw"
        className="hidden h-auto w-full dark:block"
      />
    </div>
  );
}

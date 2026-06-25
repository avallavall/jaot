"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface RevealProps {
  children: React.ReactNode;
  /** Stagger delay in milliseconds before the reveal transition starts. */
  delay?: number;
  className?: string;
}

/**
 * Fade-and-rise on scroll into view. Reveals once, then disconnects.
 *
 * Accessibility / robustness:
 * - `prefers-reduced-motion` is honored via the `motion-reduce:` utilities AND
 *   the `[data-reveal]` override in globals.css (so the SSR/no-JS state is fully
 *   visible too — the rendered DOM text is always present for crawlers).
 * - SSR renders the hidden offset state; the observer (always available in target
 *   browsers) reveals on first intersection, then disconnects.
 */
export function Reveal({ children, delay = 0, className }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.1 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      data-reveal=""
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
      className={cn(
        "transition-all duration-700 ease-out motion-reduce:transition-none",
        visible ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0",
        className,
      )}
    >
      {children}
    </div>
  );
}

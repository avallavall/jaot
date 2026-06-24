/**
 * Skip-to-content link for keyboard / screen-reader users (A11Y-04).
 * Visually hidden until focused, then appears as a fixed overlay.
 */
export function SkipLink() {
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-[100] focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:shadow-lg focus:outline-none"
    >
      Skip to content
    </a>
  );
}

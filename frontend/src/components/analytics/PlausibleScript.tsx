import Script from "next/script";

// Self-hosted Plausible — cookieless, no consent gate. Mount only inside (public)/layout.tsx.
export function PlausibleScript() {
  return (
    <Script
      defer
      data-domain="jaot.io"
      src="https://plausible.jaot.io/js/script.js"
      strategy="afterInteractive"
    />
  );
}

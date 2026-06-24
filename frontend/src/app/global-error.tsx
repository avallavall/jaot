"use client";

import Link from "next/link";

// Root error boundary: renders when the [locale] layout itself crashes
// (audit F-03). It replaces the entire document, so no i18n providers or
// globals.css are available — strings are inline English and styles are
// inline, using the vintage palette from globals.css for brand consistency.

const styles = {
  body: {
    margin: 0,
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center" as const,
    backgroundColor: "#F6F0EA",
    color: "#3A3230",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    padding: "1.5rem",
  },
  brand: {
    fontFamily: "ui-serif, Georgia, serif",
    fontSize: "1.25rem",
    color: "#5D4E47",
    marginBottom: "2rem",
    textDecoration: "none",
  },
  title: { fontSize: "1.5rem", fontWeight: 600, margin: "0 0 0.75rem" },
  message: { color: "#6B5F59", maxWidth: "28rem", margin: "0 0 2rem" },
  button: {
    backgroundColor: "#5D4E47",
    color: "#FFFFFF",
    border: "none",
    padding: "0.5rem 1.25rem",
    fontSize: "0.875rem",
    fontWeight: 500,
    cursor: "pointer",
    marginRight: "0.75rem",
  },
  link: {
    display: "inline-block",
    border: "1px solid rgba(93, 78, 71, 0.4)",
    color: "#3A3230",
    padding: "0.5rem 1.25rem",
    fontSize: "0.875rem",
    fontWeight: 500,
    textDecoration: "none",
  },
};

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body style={styles.body}>
        <Link href="/" style={styles.brand}>
          JAOT
        </Link>
        <h1 style={styles.title}>Something went wrong</h1>
        <p style={styles.message}>
          An unexpected error occurred. Please try again, or return to the home
          page if the problem persists.
          {error.digest ? ` (Error reference: ${error.digest})` : ""}
        </p>
        <div>
          <button onClick={reset} style={styles.button}>
            Try again
          </button>
          <Link href="/" style={styles.link}>
            Back to home
          </Link>
        </div>
      </body>
    </html>
  );
}

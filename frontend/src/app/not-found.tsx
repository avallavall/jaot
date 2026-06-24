import Link from "next/link";

// Root 404 for requests that never enter the [locale] tree — i.e. paths the
// next-intl middleware matcher skips (dotted paths like /foo.txt) and
// notFound() thrown by the [locale] layout itself on invalid locales
// (audit F-03). The root layout is a pass-through, so this page renders its
// own <html>/<body>; no i18n providers or globals.css are available, hence
// inline English strings and inline styles (vintage palette).

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
  code: {
    fontFamily: "ui-serif, Georgia, serif",
    fontSize: "4.5rem",
    color: "#5D4E47",
    margin: "0 0 1.5rem",
  },
  title: { fontSize: "1.5rem", fontWeight: 600, margin: "0 0 0.75rem" },
  message: { color: "#6B5F59", maxWidth: "28rem", margin: "0 0 2rem" },
  primaryLink: {
    display: "inline-block",
    backgroundColor: "#5D4E47",
    color: "#FFFFFF",
    padding: "0.5rem 1.25rem",
    fontSize: "0.875rem",
    fontWeight: 500,
    textDecoration: "none",
    marginRight: "0.75rem",
  },
  outlineLink: {
    display: "inline-block",
    border: "1px solid rgba(93, 78, 71, 0.4)",
    color: "#3A3230",
    padding: "0.5rem 1.25rem",
    fontSize: "0.875rem",
    fontWeight: 500,
    textDecoration: "none",
  },
};

export default function RootNotFound() {
  return (
    <html lang="en">
      <body style={styles.body}>
        <Link href="/" style={styles.brand}>
          JAOT
        </Link>
        <p style={styles.code} aria-hidden="true">
          404
        </p>
        <h1 style={styles.title}>Page not found</h1>
        <p style={styles.message}>
          The page you are looking for does not exist or has been moved.
        </p>
        <div>
          <Link href="/" style={styles.primaryLink}>
            Back to home
          </Link>
          <Link href="/marketplace" style={styles.outlineLink}>
            Browse the marketplace
          </Link>
        </div>
      </body>
    </html>
  );
}

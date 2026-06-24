import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { JsonLd } from "../JsonLd";
import { buildOrganizationSchema } from "@/lib/seo/schemas/organization";

describe("JsonLd", () => {
  it("renders a <script type='application/ld+json'> element", () => {
    const data = buildOrganizationSchema("https://jaot.io");
    const { container } = render(<JsonLd data={data} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
  });

  it("rendered textContent parses back to JSON with @type Organization", () => {
    const data = buildOrganizationSchema("https://jaot.io");
    const { container } = render(<JsonLd data={data} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    const parsed = JSON.parse(script!.textContent ?? "{}") as Record<string, unknown>;
    expect(parsed["@type"]).toBe("Organization");
  });

  it("escapes < as \\u003c in the serialized payload", () => {
    // Hostile input: name contains </script><script>alert(1)
    const hostile = {
      "@context": "https://schema.org" as const,
      "@type": "Organization" as const,
      name: "x</script><script>alert(1)",
    };
    const { container } = render(<JsonLd data={hostile} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    const rawHtml = script!.innerHTML;
    // The literal </script> sequence MUST NOT appear in the payload
    expect(rawHtml).not.toContain("</script");
    // The < char MUST be unicode-escaped
    expect(rawHtml).toContain("\\u003c");
  });

  it("escapes > as \\u003e in the serialized payload", () => {
    const hostile = {
      "@context": "https://schema.org" as const,
      "@type": "Organization" as const,
      name: "x>y",
    };
    const { container } = render(<JsonLd data={hostile} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    const rawHtml = script!.innerHTML;
    expect(rawHtml).toContain("\\u003e");
    expect(rawHtml).not.toContain('"x>y"');
  });

  it("escapes & as \\u0026 in the serialized payload", () => {
    const hostile = {
      "@context": "https://schema.org" as const,
      "@type": "Organization" as const,
      name: "JAOT & Co",
    };
    const { container } = render(<JsonLd data={hostile} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    const rawHtml = script!.innerHTML;
    expect(rawHtml).toContain("\\u0026");
    expect(rawHtml).not.toContain('"JAOT & Co"');
  });

  it("escaped payload still parses back via JSON.parse", () => {
    const hostile = {
      "@context": "https://schema.org" as const,
      "@type": "Organization" as const,
      name: 'x</script><script>alert(1) & "hello"',
    };
    const { container } = render(<JsonLd data={hostile} />);
    const script = container.querySelector('script[type="application/ld+json"]');
    // The textContent is the unescaped version - JSON.parse should still work
    const parsed = JSON.parse(script!.textContent ?? "{}") as Record<string, unknown>;
    expect(parsed.name).toBe('x</script><script>alert(1) & "hello"');
  });
});

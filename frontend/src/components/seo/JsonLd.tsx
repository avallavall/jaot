import type { Thing, WithContext } from "schema-dts";

interface JsonLdProps {
  data: WithContext<Thing>;
}

// XSS guard: JSON.stringify produces </script> sequences when string values contain
// markup. Replace with unicode escapes before embedding in dangerouslySetInnerHTML.
// This is the V5 input-validation control (ASVS) for JSON-LD injection.
// The escaping is the deliverable shape — 13.3 wires this to routes with user-supplied
// strings (model names/descriptions) so the control must exist now.
export function JsonLd({ data }: JsonLdProps) {
  const json = JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: json }}
    />
  );
}

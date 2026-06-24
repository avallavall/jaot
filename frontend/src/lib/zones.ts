export type FeedbackZone = "builder" | "solver" | "llm" | "results" | "dashboard" | "models";

const ZONE_MAP: [RegExp, FeedbackZone][] = [
  [/^\/builder\/[^/]+\/chat/, "llm"], // Chat subpage before generic builder
  [/^\/builder/, "builder"],
  [/^\/solve\/executions/, "results"],
  [/^\/solve/, "solver"],
  [/^\/marketplace/, "models"],
  [/^\/workspace\/usage/, "dashboard"],
  [/^\/workspace/, "dashboard"],
  [/^\/admin/, "dashboard"],
];

export function getZoneFromPath(pathname: string): FeedbackZone {
  for (const [pattern, zone] of ZONE_MAP) {
    if (pattern.test(pathname)) return zone;
  }
  return "dashboard"; // fallback for unmapped routes
}

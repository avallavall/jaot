import { describe, it, expect } from "vitest";
import { guides, guidesByDomain, DOMAIN_CLUSTERS } from "../guide-data";

const ALL_CATEGORIES = [
  "finance", "logistics", "manufacturing", "agriculture", "healthcare", "energy",
  "retail", "hr", "general", "supply_chain", "facility_location", "network_graph",
  "cutting_packing", "telecom", "transportation", "environmental", "sports",
  "education", "real_estate", "mining", "water_management", "aerospace",
  "pharmaceutical", "chemical_engineering", "forestry", "maritime", "railway",
  "food_beverage", "textile", "construction", "advertising_media", "warehouse",
  "insurance", "government",
];

describe("guide-data", () => {
  it("has exactly 34 guide entries", () => {
    expect(guides).toHaveLength(34);
  });

  it("covers every ModelCategory enum value", () => {
    const categories = guides.map((g) => g.category);
    for (const cat of ALL_CATEGORIES) {
      expect(categories).toContain(cat);
    }
  });

  it("every guide has a valid difficulty", () => {
    const validDifficulties = ["beginner", "intermediate", "advanced"];
    for (const guide of guides) {
      expect(validDifficulties).toContain(guide.difficulty);
    }
  });

  it("DOMAIN_CLUSTERS covers all 34 category values", () => {
    const allClusteredCategories = Object.values(DOMAIN_CLUSTERS).flat();
    expect(allClusteredCategories).toHaveLength(34);
    for (const cat of ALL_CATEGORIES) {
      expect(allClusteredCategories).toContain(cat);
    }
  });

  it("guidesByDomain groups all 34 guides with no orphans", () => {
    const totalGuides = Object.values(guidesByDomain).reduce(
      (sum, arr) => sum + arr.length,
      0
    );
    expect(totalGuides).toBe(34);

    // No empty domains
    for (const [, domainGuides] of Object.entries(guidesByDomain)) {
      expect(domainGuides.length).toBeGreaterThan(0);
    }
  });

  it("guidesByDomain has approximately 10 domain clusters", () => {
    const domainCount = Object.keys(guidesByDomain).length;
    expect(domainCount).toBeGreaterThanOrEqual(9);
    expect(domainCount).toBeLessThanOrEqual(12);
  });

  it("every guide has required fields", () => {
    for (const guide of guides) {
      expect(guide.title).toBeTruthy();
      expect(guide.description).toBeTruthy();
      expect(guide.slug).toBeTruthy();
      expect(guide.category).toBeTruthy();
      expect(guide.domain).toBeTruthy();
      expect(guide.templateCount).toBeGreaterThanOrEqual(1);
    }
  });
});

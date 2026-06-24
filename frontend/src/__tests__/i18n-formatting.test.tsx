import { describe, it, expect } from "vitest";
import { IntlMessageFormat } from "intl-messageformat";

describe("ICU Formatting Patterns", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const enMessages = require("../../messages/en.json");

  it("renders plural patterns correctly for credits", () => {
    const msg = new IntlMessageFormat(enMessages.common.credits, "en");
    expect(msg.format({ count: 1 })).toBe("1 credit");
    expect(msg.format({ count: 5 })).toBe("5 credits");
    expect(msg.format({ count: 0 })).toBe("0 credits");
  });

  it("renders plural patterns correctly for items", () => {
    const msg = new IntlMessageFormat(enMessages.common.itemCount, "en");
    expect(msg.format({ count: 1 })).toBe("1 item");
    expect(msg.format({ count: 42 })).toBe("42 items");
  });

  it("validates all ICU messages parse without errors", () => {
    const walkMessages = (obj: Record<string, unknown>, path = "") => {
      for (const [key, value] of Object.entries(obj)) {
        const fullPath = path ? `${path}.${key}` : key;
        if (typeof value === "string") {
          expect(() => new IntlMessageFormat(value, "en")).not.toThrow();
        } else if (typeof value === "object" && value !== null) {
          walkMessages(value as Record<string, unknown>, fullPath);
        }
      }
    };
    walkMessages(enMessages);
  });
});

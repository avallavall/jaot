import { describe, expect, it } from "vitest";
import { getPasswordStrength, isPasswordTooSimple } from "@/lib/password-strength";

describe("getPasswordStrength", () => {
  it("calls a long run of one character class weak", () => {
    expect(getPasswordStrength("aaaaaaaaaaaa").level).toBe("weak");
  });

  it("calls a mixed password strong", () => {
    expect(getPasswordStrength("Correct-Horse-9").level).toBe("strong");
  });
});

describe("isPasswordTooSimple", () => {
  // The meter called twelve identical letters "weak" and the account was
  // created anyway. Length is not variety.
  it("refuses a password of one repeated letter", () => {
    expect(isPasswordTooSimple("aaaaaaaaaaaa")).toBe(true);
  });

  it("refuses any run of lower-case letters, however long", () => {
    expect(isPasswordTooSimple("correcthorsebattery")).toBe(true);
  });

  it.each(["Aaaaaaaaaaaa", "aaaaaaaaaaa1", "aaaaaaaaaaa!"])("accepts %s", (password) => {
    expect(isPasswordTooSimple(password)).toBe(false);
  });
});

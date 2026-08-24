import { describe, it, expect } from "vitest";
import {
  EXPIRED_PARAM,
  RETURN_PARAM,
  defaultLandingPath,
  loginPathReturningTo,
  safeReturnPath,
} from "../return-path";

describe("safeReturnPath", () => {
  it("keeps an in-app path, query string and all", () => {
    expect(safeReturnPath("/workspace/api-keys", "/studio")).toBe("/workspace/api-keys");
    expect(safeReturnPath("/solve/executions/compare?a=1&b=2", "/studio")).toBe(
      "/solve/executions/compare?a=1&b=2",
    );
  });

  // CONTRACT-TEST: `next` is attacker-controlled — it must never leave the site.
  it.each([
    "https://evil.example/steal",
    "//evil.example/steal",
    "/\\evil.example/steal",
    "http://evil.example",
    "javascript:alert(1)",
    "evil.example",
  ])("refuses %s", (hostile) => {
    expect(safeReturnPath(hostile, "/studio")).toBe("/studio");
  });

  it("refuses the auth pages themselves, which would loop", () => {
    expect(safeReturnPath("/login", "/studio")).toBe("/studio");
    expect(safeReturnPath("/login?next=%2Flogin", "/studio")).toBe("/studio");
    expect(safeReturnPath("/signup", "/studio")).toBe("/studio");
    expect(safeReturnPath("/reset-password?token=x", "/studio")).toBe("/studio");
  });

  it("falls back on nothing at all", () => {
    expect(safeReturnPath(null, "/studio")).toBe("/studio");
    expect(safeReturnPath(undefined, "/studio")).toBe("/studio");
    expect(safeReturnPath("", "/studio")).toBe("/studio");
  });
});

describe("loginPathReturningTo", () => {
  it("encodes the destination so a query string survives the round trip", () => {
    const url = loginPathReturningTo("/solve/executions", "?status=cancelled");
    expect(url).toBe(`/login?${RETURN_PARAM}=%2Fsolve%2Fexecutions%3Fstatus%3Dcancelled`);

    const returned = new URLSearchParams(url.split("?")[1]).get(RETURN_PARAM);
    expect(safeReturnPath(returned, "/studio")).toBe("/solve/executions?status=cancelled");
  });

  it("does not bother carrying a destination it would refuse anyway", () => {
    expect(loginPathReturningTo("/login", "")).toBe("/login");
  });

  // The login page shows "your session expired" off this flag. An anonymous
  // visitor who opened a protected page never had a session, so they must not
  // be told one ended.
  it("says the session expired only when one did", () => {
    expect(loginPathReturningTo("/studio", "")).toBe(`/login?${RETURN_PARAM}=%2Fstudio`);
    expect(loginPathReturningTo("/studio", "", true)).toBe(
      `/login?${RETURN_PARAM}=%2Fstudio&${EXPIRED_PARAM}=1`,
    );
    expect(loginPathReturningTo("/login", "", true)).toBe(`/login?${EXPIRED_PARAM}=1`);
  });
});

describe("defaultLandingPath", () => {
  it("sends admins to the admin area and everyone else to the studio", () => {
    expect(defaultLandingPath(true)).toBe("/admin");
    expect(defaultLandingPath(false)).toBe("/studio");
    expect(defaultLandingPath(undefined)).toBe("/studio");
  });
});

import { describe, expect, it } from "vitest";
import { apiDate } from "../dates";

describe("apiDate", () => {
  it("treats a naive backend timestamp as UTC", () => {
    // The API serializes naive UTC; parsing it as local shifted every display
    // by the viewer's offset (the "hace 2 horas" live bug).
    expect(apiDate("2026-07-04T09:08:27.717655").getTime()).toBe(
      Date.UTC(2026, 6, 4, 9, 8, 27, 717),
    );
  });

  it("leaves explicit UTC and offset timestamps untouched", () => {
    expect(apiDate("2026-07-04T09:08:27Z").getTime()).toBe(Date.UTC(2026, 6, 4, 9, 8, 27));
    expect(apiDate("2026-07-04T11:08:27+02:00").getTime()).toBe(Date.UTC(2026, 6, 4, 9, 8, 27));
    expect(apiDate("2026-07-04T11:08:27+0200").getTime()).toBe(Date.UTC(2026, 6, 4, 9, 8, 27));
  });

  it("round-trips client-generated ISO strings", () => {
    const iso = new Date().toISOString(); // always ends in Z
    expect(apiDate(iso).toISOString()).toBe(iso);
  });
});

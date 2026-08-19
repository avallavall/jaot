import { describe, expect, it } from "vitest";
import { apiDate, relativeTimeBase } from "../dates";

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

describe("relativeTimeBase", () => {
  // next-intl's useNow() only advances on the interval it is given, so an event
  // that happens between two ticks is newer than the clock. The Solve panel
  // asked for no interval at all: "Last run: solved · objective 7 · in 3
  // seconds", and it never moved.
  it("measures a just-finished run against itself, never against a stale clock", () => {
    const now = new Date("2026-08-19T10:00:00Z");
    const finished = new Date("2026-08-19T10:00:03Z");

    expect(relativeTimeBase(now, finished)).toEqual(finished);
  });

  it("leaves a past event measured against the clock", () => {
    const now = new Date("2026-08-19T10:00:00Z");
    const finished = new Date("2026-08-19T09:59:30Z");

    expect(relativeTimeBase(now, finished)).toEqual(now);
  });

  it("treats the same instant as the clock", () => {
    const instant = new Date("2026-08-19T10:00:00Z");

    expect(relativeTimeBase(instant, new Date(instant))).toEqual(instant);
  });
});

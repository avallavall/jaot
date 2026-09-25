import { describe, it, expect, vi } from "vitest";

const { redirect } = vi.hoisted(() => ({ redirect: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({ redirect }));

import LegacySolvePublishPage from "../page";

describe("the old /solve/<model>/publish address", () => {
  it("opens the studio's publish page, not the Build tab", async () => {
    await LegacySolvePublishPage({ params: Promise.resolve({ locale: "es", modelId: "mp_1" }) });
    expect(redirect).toHaveBeenCalledWith({ href: "/studio/mp_1/publish", locale: "es" });
  });
});

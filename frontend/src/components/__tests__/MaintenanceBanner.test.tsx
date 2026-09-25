/**
 * The maintenance text appears once.
 *
 * On the maintenance page, the page's own API calls answer 503 "maintenance",
 * and the overlay drew the same notice again on top of the page. The text was
 * in the DOM twice, and a screen reader read it twice (browser QA, 2026-09-24).
 */
import { describe, it, expect } from "vitest";
import { act, render, screen } from "@testing-library/react";

import { MaintenanceBanner } from "../MaintenanceBanner";
import { MAINTENANCE_PAGE_ATTRIBUTE } from "@/lib/maintenance";

function apiSaysMaintenance() {
  act(() => {
    window.dispatchEvent(
      new CustomEvent("jaot:maintenance", {
        detail: { status: "maintenance", detail: "JAOT is currently under maintenance." },
      }),
    );
  });
}

describe("the maintenance overlay", () => {
  it("covers an ordinary page when the API says the site is in maintenance", () => {
    render(<MaintenanceBanner />);

    apiSaysMaintenance();

    expect(screen.getByRole("heading", { name: "maintenance.heading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "maintenance.retry" })).toBeInTheDocument();
  });

  it("stays away from the maintenance page, which already says it", () => {
    render(
      <>
        <div {...{ [MAINTENANCE_PAGE_ATTRIBUTE]: "" }}>
          <h1>maintenance.heading</h1>
        </div>
        <MaintenanceBanner />
      </>,
    );

    apiSaysMaintenance();

    expect(screen.getAllByRole("heading", { name: "maintenance.heading" })).toHaveLength(1);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

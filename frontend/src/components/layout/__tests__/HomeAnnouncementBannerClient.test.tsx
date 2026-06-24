import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomeAnnouncementBannerClient } from "../HomeAnnouncementBannerClient";

vi.mock("next-intl", () => ({
  useTranslations: () => {
    const t = (key: string) => key;
    return t;
  },
}));

describe("HomeAnnouncementBannerClient", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    // Some tests switch back to real timers; only flush when still mocked.
    if (vi.isFakeTimers()) {
      vi.runOnlyPendingTimers();
      vi.useRealTimers();
    }
  });

  it("renders the single provided message", () => {
    render(
      <HomeAnnouncementBannerClient messages={["Hello world"]} rotationSeconds={5} />,
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("rotates through messages on the configured interval", () => {
    render(
      <HomeAnnouncementBannerClient
        messages={["one", "two", "three"]}
        rotationSeconds={5}
      />,
    );
    expect(screen.getByText("one")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("two")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("three")).toBeInTheDocument();

    // Wraps back to the first message.
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("one")).toBeInTheDocument();
  });

  it("does not start an interval when there is only one message", () => {
    const setInterval = vi.spyOn(window, "setInterval");
    render(
      <HomeAnnouncementBannerClient messages={["solo"]} rotationSeconds={5} />,
    );
    expect(setInterval).not.toHaveBeenCalled();
  });

  it("disappears and persists dismissal to localStorage when the close button is clicked", async () => {
    vi.useRealTimers(); // userEvent needs real timers
    const user = userEvent.setup();
    const { container } = render(
      <HomeAnnouncementBannerClient
        messages={["Closeable"]}
        rotationSeconds={5}
      />,
    );
    expect(screen.getByText("Closeable")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "dismiss" }));

    expect(container.firstChild).toBeNull();
    const keys = Object.keys(window.localStorage);
    expect(keys.some((k) => k.startsWith("jaot.banner.dismissed."))).toBe(true);
  });

  it("stays hidden on remount when the same messages were previously dismissed", () => {
    // The component's storage key is "jaot.banner.dismissed." + messages.join("|").
    window.localStorage.setItem("jaot.banner.dismissed.persisted", "1");

    const { container } = render(
      <HomeAnnouncementBannerClient
        messages={["persisted"]}
        rotationSeconds={5}
      />,
    );

    // After the effect runs the banner is removed. flush effects:
    act(() => {});
    expect(container.firstChild).toBeNull();
  });

  it("re-renders when messages change (different localStorage key)", () => {
    // Dismiss state for ["original"] should NOT suppress ["updated"].
    window.localStorage.setItem("jaot.banner.dismissed.original", "1");

    render(
      <HomeAnnouncementBannerClient messages={["updated"]} rotationSeconds={5} />,
    );
    expect(screen.getByText("updated")).toBeInTheDocument();
  });
});

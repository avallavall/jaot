import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pollEvery } from "../poll";

describe("pollEvery", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not start a tick while the last one is still out", async () => {
    let finish: () => void = () => undefined;
    const tick = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const stop = pollEvery(tick, 1000, { immediately: true });

    await vi.advanceTimersByTimeAsync(3500);
    expect(tick).toHaveBeenCalledTimes(1);

    finish();
    await vi.advanceTimersByTimeAsync(1000);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("keeps going after a tick that fails, and stops when told", async () => {
    const tick = vi.fn().mockRejectedValueOnce(new Error("blip")).mockResolvedValue(undefined);
    const stop = pollEvery(tick, 1000);

    await vi.advanceTimersByTimeAsync(3000);
    expect(tick).toHaveBeenCalledTimes(3);

    stop();
    await vi.advanceTimersByTimeAsync(3000);
    expect(tick).toHaveBeenCalledTimes(3);
  });
});

import { describe, it, expect, vi, beforeEach, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import type { ModelExecution } from "@/lib/types";

// Stable mock objects created before module loading via vi.hoisted().
// Using vi.fn() directly inside the mock factory creates NEW function references
// on every render — these land in the useEffect dependency array ([disconnectWs])
// and trigger an infinite render loop that OOMs the worker at ~41 MB/s.
const { mockWs, mockApi } = vi.hoisted(() => ({
  mockWs: {
    isConnected: false,
    lastMessage: null as null,
    connect: vi.fn(),
    disconnect: vi.fn(),
    sendMessage: vi.fn(),
  },
  mockApi: {
    request: vi.fn(),
    getAsyncTaskStatus: vi.fn(),
  },
}));

vi.mock("@/hooks/useWebSocket", () => ({
  useExecutionWebSocket: vi.fn().mockReturnValue(mockWs),
}));

vi.mock("@/lib/api", () => ({
  api: mockApi,
}));

import { ExecutionProgress } from "../ExecutionProgress";
import { useExecutionWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";

// TODO: fix infinite render loop that OOMs the vitest worker (see vi.hoisted comment above)
describe.skip("ExecutionProgress", () => {
  afterAll(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    // Re-apply after clearAllMocks resets call counts (implementation survives clearAllMocks)
    vi.mocked(api.getAsyncTaskStatus).mockResolvedValue({
      task_id: "task1",
      status: "running",
      progress: 0.5,
    });
  });

  it("returns null when executionId is null", () => {
    const { container } = render(<ExecutionProgress executionId={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders Execution Progress header when executionId is provided", () => {
    render(<ExecutionProgress executionId="exec-123" />);
    expect(screen.getByText("solve.progress.title")).toBeInTheDocument();
  });

  it("shows Disconnected when WebSocket is not connected", () => {
    vi.mocked(useExecutionWebSocket).mockReturnValue({
      isConnected: false,
      lastMessage: null,
      connect: vi.fn(),
      disconnect: vi.fn(),
      sendMessage: vi.fn(),
    });

    render(<ExecutionProgress executionId="exec-123" />);
    expect(screen.getByText("solve.progress.disconnected")).toBeInTheDocument();
  });

  it("shows Connected when WebSocket is connected", () => {
    vi.mocked(useExecutionWebSocket).mockReturnValue({
      isConnected: true,
      lastMessage: null,
      connect: vi.fn(),
      disconnect: vi.fn(),
      sendMessage: vi.fn(),
    });

    render(<ExecutionProgress executionId="exec-123" />);
    expect(screen.getByText("solve.progress.connected")).toBeInTheDocument();
  });

  it("shows Cancel Execution button when status is pending", () => {
    render(<ExecutionProgress executionId="exec-123" />);
    expect(screen.getByRole("button", { name: /cancelExecution/i })).toBeInTheDocument();
  });

  it("calls onComplete when polling returns completed status", async () => {
    const onComplete = vi.fn();
    vi.mocked(api.getAsyncTaskStatus).mockResolvedValue({
      task_id: "task1",
      status: "completed",
      result: { objective_value: 42.5 } as unknown as ModelExecution,
    });

    render(<ExecutionProgress executionId="exec-123" onComplete={onComplete} />);

    await waitFor(() => expect(onComplete).toHaveBeenCalled(), { timeout: 2000 });
  });

  it("calls onError when polling returns failed status", async () => {
    const onError = vi.fn();
    vi.mocked(api.getAsyncTaskStatus).mockResolvedValue({
      task_id: "task1",
      status: "failed",
      error: "Solver timeout",
    });

    render(<ExecutionProgress executionId="exec-123" onError={onError} />);

    await waitFor(() => expect(onError).toHaveBeenCalledWith("Solver timeout"), { timeout: 2000 });
  });

  it("calls cancel endpoint and onCancel when Cancel button is clicked", async () => {
    vi.mocked(api.request).mockResolvedValue({});
    const onCancel = vi.fn();

    render(<ExecutionProgress executionId="exec-123" onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: /cancelExecution/i }));

    await waitFor(() => {
      expect(api.request).toHaveBeenCalledWith(
        expect.stringContaining("exec-123"),
        expect.objectContaining({ method: "POST" })
      );
      expect(onCancel).toHaveBeenCalled();
    }, { timeout: 2000 });
  });

  // === Accessibility: aria-live tests (A11Y-05) ===
  // These tests are RED -- they verify features that don't exist yet.

  it("has an aria-live region for status announcements", () => {
    const { container } = render(<ExecutionProgress executionId="exec-123" />);

    // There should be an aria-live="polite" region to announce status changes
    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).not.toBeNull();
  });

  it("announces 'Solving started' when status changes to running", async () => {
    // Mock polling to return running status
    vi.mocked(api.getAsyncTaskStatus).mockResolvedValue({
      task_id: "task1",
      status: "running",
      progress: 0.1,
    });

    const { container } = render(<ExecutionProgress executionId="exec-123" />);

    // Wait for the aria-live region to announce the status change
    await waitFor(() => {
      const liveRegion = container.querySelector('[aria-live="polite"]');
      expect(liveRegion).not.toBeNull();
      expect(liveRegion?.textContent).toMatch(/announceSolvingStarted/i);
    }, { timeout: 2000 });
  });

  it("has aria-busy on container while solving", () => {
    // Default mock has status "running" via polling
    const { container } = render(<ExecutionProgress executionId="exec-123" />);

    // The main card container should indicate it's busy while solving
    // (firstChild is the aria-live region, the card is the next sibling)
    const busyContainer = container.querySelector('[aria-busy]');
    expect(busyContainer).not.toBeNull();
    expect(busyContainer!.getAttribute("aria-busy")).toBe("true");
  });
});

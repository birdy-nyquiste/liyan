import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Throws(): never {
  throw new Error("the panel could not render");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs a caught error itself, and the boundary logs it too. Both are
    // wanted in a real popup and neither is wanted in the test output.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stays out of the way when nothing is wrong", () => {
    render(
      <ErrorBoundary>
        <p>主屏</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("主屏")).toBeInTheDocument();
  });

  /**
   * The failure this exists for. A popup that throws while rendering has no
   * reload arrow, no address bar and no back button, so a blank panel is a dead
   * end — and reopening it runs the same code again.
   */
  it("replaces a blank popup with something to press", async () => {
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      reload,
    } as unknown as Location);

    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("插件出了点问题，没能显示。");
    await userEvent.click(screen.getByRole("button", { name: "重新载入" }));
    expect(reload).toHaveBeenCalled();
  });

  /**
   * The one thing a user in this state actually wants to know. 来源 already
   * captured are on the server and were paid for; a panel that failed to draw
   * has not lost them, and saying so is the difference between an annoyance
   * and a reason to think the work is gone.
   */
  it("says that nothing collected has been lost", () => {
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/不会因此丢失/)).toBeInTheDocument();
  });
});

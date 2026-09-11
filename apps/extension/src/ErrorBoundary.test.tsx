import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Throws(): never {
  throw new Error("the panel could not render");
}

/**
 * What Chrome's language is set to, for the length of one test.
 *
 * The fallback cannot be handed a language — it is the thing that catches the
 * context that would carry one failing — so it reads the browser directly, and
 * that is what a test has to move.
 */
function browserLanguage(tag: string) {
  vi.spyOn(navigator, "language", "get").mockReturnValue(tag);
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs a caught error itself, and the boundary logs it too. Both are
    // wanted in a real popup and neither is wanted in the test output.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    browserLanguage("zh-CN");
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

  /**
   * The panel follows the browser, and this is the one screen that cannot be
   * told what the browser said. A fallback that answered a reader of English
   * in Chinese would be the panel's last words and its least useful ones.
   */
  it("speaks the browser's language, not the panel's", () => {
    browserLanguage("en-GB");
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Something went wrong and the panel could not be shown.",
    );
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });
});

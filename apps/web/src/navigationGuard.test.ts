import { describe, expect, it, vi } from "vitest";

import { installHistoryGuard, setHistoryGuard } from "./navigationGuard";

describe("history navigation guard", () => {
  it("keeps the protected URL until the writer answers, for Back and Forward alike", () => {
    installHistoryGuard();
    const onBlocked = vi.fn();

    for (const targetIndex of [0, 2]) {
      window.history.replaceState({ idx: targetIndex }, "", "/publications");
      setHistoryGuard({
        onBlocked,
        protectedState: { idx: 1, key: "protected" },
        protectedUrl: `${window.location.origin}/task`,
      });

      window.dispatchEvent(new PopStateEvent("popstate", { state: { idx: targetIndex } }));

      // Reverted first: a popstate cannot be awaited, so the page is put back
      // and the question asked afterwards.
      expect(window.location.pathname).toBe("/task");
      expect(window.history.state).toMatchObject({ idx: targetIndex + 1, key: "protected" });
    }
    expect(onBlocked).toHaveBeenCalledTimes(2);
    setHistoryGuard(null);
  });

  it("replays the navigation once it is allowed", () => {
    installHistoryGuard();
    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    let allow: (() => void) | null = null;

    window.history.replaceState({ idx: 0 }, "", "/publications");
    setHistoryGuard({
      onBlocked: (replay) => { allow = replay; },
      protectedState: { idx: 1, key: "protected" },
      protectedUrl: `${window.location.origin}/task`,
    });
    window.dispatchEvent(new PopStateEvent("popstate", { state: { idx: 0 } }));

    allow!();
    // One entry deeper than the target, so a single step back lands on it.
    expect(go).toHaveBeenCalledWith(-1);

    // The guard is spent: a second attempt is no longer intercepted.
    window.dispatchEvent(new PopStateEvent("popstate", { state: { idx: 0 } }));
    expect(go).toHaveBeenCalledTimes(1);

    go.mockRestore();
    setHistoryGuard(null);
  });
});

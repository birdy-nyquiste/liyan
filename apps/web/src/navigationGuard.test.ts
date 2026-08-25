import { describe, expect, it, vi } from "vitest";

import { installHistoryGuard, setHistoryGuard } from "./navigationGuard";

describe("history navigation guard", () => {
  it("keeps the protected URL when either Back or Forward is rejected", () => {
    installHistoryGuard();
    const onAllowed = vi.fn();
    const confirm = vi.fn(() => false);

    for (const targetIndex of [0, 2]) {
      window.history.replaceState({ idx: targetIndex }, "", "/publications");
      setHistoryGuard({
        confirm,
        onAllowed,
        protectedState: { idx: 1, key: "protected" },
        protectedUrl: `${window.location.origin}/task`,
      });

      window.dispatchEvent(new PopStateEvent("popstate", { state: { idx: targetIndex } }));

      expect(window.location.pathname).toBe("/task");
      expect(window.history.state).toMatchObject({ idx: targetIndex + 1, key: "protected" });
    }
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(onAllowed).not.toHaveBeenCalled();
    setHistoryGuard(null);
  });
});

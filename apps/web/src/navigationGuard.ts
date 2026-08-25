type HistoryGuard = {
  /**
   * Called after the attempted navigation has been reverted. Ask the writer
   * whatever needs asking, then call `replay` to let the navigation happen, or
   * do nothing to keep them where they are.
   */
  onBlocked(replay: () => void): void;
  protectedState: unknown;
  protectedUrl: string;
};

let guard: HistoryGuard | null = null;
let installed = false;

/**
 * Install before React Router so rejected POPs never reach its listener.
 *
 * A popstate decision has to be made synchronously — there is no awaiting the
 * browser — so this always reverts first and asks afterwards. That is also what
 * makes an in-page dialog possible here: `window.confirm` is the only thing that
 * can answer inside the handler, and a browser that suppresses it answers
 * "false" on the writer's behalf, silently trapping them on the page.
 */
export function installHistoryGuard(): void {
  if (installed) return;
  installed = true;
  window.addEventListener("popstate", (event) => {
    const active = guard;
    if (!active) return;
    event.stopImmediatePropagation();
    const targetIndex = event.state?.idx;
    window.history.pushState(
      typeof targetIndex === "number"
        ? { ...(active.protectedState as object), idx: targetIndex + 1 }
        : active.protectedState,
      "",
      active.protectedUrl,
    );
    // One entry deeper than the target now, so going back once lands on it —
    // and fires the popstate React Router is waiting for.
    active.onBlocked(() => {
      guard = null;
      window.history.go(-1);
    });
  });
}

export function setHistoryGuard(next: HistoryGuard | null): void {
  guard = next;
}

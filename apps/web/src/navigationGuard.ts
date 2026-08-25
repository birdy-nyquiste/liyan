type HistoryGuard = {
  confirm(): boolean;
  onAllowed(): void;
  protectedState: unknown;
  protectedUrl: string;
};

let guard: HistoryGuard | null = null;
let installed = false;

/** Install before React Router so rejected POPs never reach its listener. */
export function installHistoryGuard(): void {
  if (installed) return;
  installed = true;
  window.addEventListener("popstate", (event) => {
    const active = guard;
    if (!active) return;
    const allowed = active.confirm();
    if (allowed) {
      guard = null;
      active.onAllowed();
      return;
    }
    event.stopImmediatePropagation();
    const targetIndex = event.state?.idx;
    window.history.pushState(
      typeof targetIndex === "number"
        ? { ...(active.protectedState as object), idx: targetIndex + 1 }
        : active.protectedState,
      "",
      active.protectedUrl,
    );
  });
}

export function setHistoryGuard(next: HistoryGuard | null): void {
  guard = next;
}

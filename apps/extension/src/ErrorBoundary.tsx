import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * The last thing between a thrown error and a blank popup.
 *
 * A popup has no address bar, no reload arrow and no back button, so a panel
 * that throws while rendering leaves the user holding a white rectangle with
 * nothing in it and no way to act — and reopening it runs the same code again.
 * That is the whole reason this exists: not to explain the error, which the
 * user cannot do anything about, but to leave one button that can.
 *
 * `location.reload()` is a real recovery here rather than a gesture. The panel
 * keeps nothing it needs in memory — the session and the open basket are both
 * in `chrome.storage` — so a reload is the same fresh start that closing and
 * reopening would be, without the user having to guess that that would help.
 */
type Props = { children: ReactNode };
type State = { failed: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The popup's console survives the popup being destroyed only if it was
    // already open, which is rarely. It is logged anyway: during development
    // and while inspecting a published build this is the only trace there is.
    console.error("panel failed to render", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="panel">
        <div className="panel__body">
          <p className="form-error" role="alert">
            插件出了点问题，没能显示。
          </p>
          <button className="button" type="button" onClick={() => location.reload()}>
            重新载入
          </button>
          <p className="form-hint">
            收集中的来源都保存在立言阁，不会因此丢失。反复出现请联系 birdyyao@nyquiste.com。
          </p>
        </div>
      </div>
    );
  }
}

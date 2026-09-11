import { Component, type ErrorInfo, type ReactNode } from "react";

import { preferredLocale } from "./locale";

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

/**
 * Its three sentences, carried rather than looked up.
 *
 * Everything else the panel says comes from 工作台's table through a React
 * context — and this is the component that catches the context failing. A
 * fallback that needs the thing it is a fallback for is no fallback at all, so
 * these are written twice here and nowhere else.
 */
const COPY = {
  zh: {
    failed: "插件出了点问题，没能显示。",
    reload: "重新载入",
    reassurance:
      "收集中的来源都保存在立言阁，不会因此丢失。反复出现请联系 birdyyao@nyquiste.com。",
  },
  en: {
    failed: "Something went wrong and the panel could not be shown.",
    reload: "Reload",
    reassurance:
      "Sources you have collected are stored in LiYan Studio and are not lost. If this keeps happening, contact birdyyao@nyquiste.com.",
  },
};

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
    const copy = COPY[preferredLocale()];
    return (
      <div className="panel">
        <div className="panel__body">
          <p className="form-error" role="alert">
            {copy.failed}
          </p>
          <button className="button" type="button" onClick={() => location.reload()}>
            {copy.reload}
          </button>
          <p className="form-hint">{copy.reassurance}</p>
        </div>
      </div>
    );
  }
}

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";

import { ErrorBoundary } from "./ErrorBoundary";
import { preferredLocale } from "./locale";
import { Panel } from "./Panel";
import "./panel.css";

// "system" is the workbench's own name for following the browser, and the
// panel has no settings of its own to offer instead: it is open for seconds at
// a time, and a theme toggle in it would be a second place to set one thing.
document.documentElement.dataset.theme = "system";

// `popup.html` cannot declare this: the language is the browser's, and the
// document is written before anything has asked what it is. Setting it here is
// what makes a screen reader read the panel in the language it is drawn in.
const locale = preferredLocale();
document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Outside the provider, so that the provider failing is caught too —
        which is why the fallback picks its own language rather than being
        handed one. */}
    <ErrorBoundary>
      <InterfaceLocaleProvider locale={locale}>
        <Panel />
      </InterfaceLocaleProvider>
    </ErrorBoundary>
  </StrictMode>,
);

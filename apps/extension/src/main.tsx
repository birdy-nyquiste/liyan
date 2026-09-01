import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";

import { Panel } from "./Panel";
import "./panel.css";

// "system" is the workbench's own name for following the browser, and the
// panel has no settings of its own to offer instead: it is open for seconds at
// a time, and a theme toggle in it would be a second place to set one thing.
document.documentElement.dataset.theme = "system";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <InterfaceLocaleProvider locale="zh">
      <Panel />
    </InterfaceLocaleProvider>
  </StrictMode>,
);

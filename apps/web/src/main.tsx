import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { initialiseMonitoring } from "./monitoring";

// Before the first render, so a crash during mount is still reported. Without
// VITE_SENTRY_DSN this does nothing at all, which is what local runs want.
initialiseMonitoring(import.meta.env.VITE_SENTRY_DSN);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

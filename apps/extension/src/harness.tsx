/**
 * The panel, outside Chrome.
 *
 * There is no way to load an extension into a headless browser, so this page
 * renders the real `Panel` against the real API with the two things Chrome
 * would otherwise provide stubbed: `chrome.*`, and a signed-in session. Point
 * it at `scripts/e2e_server.py`, where any bearer token is a signed-in writer.
 *
 * It is not built: `vite.config.ts` names `popup.html` as the only input, so
 * this page exists during `npm run dev:extension` and never ships.
 *
 *     ?url=…&title=…   the page the "current tab" is showing
 *
 * It has already earned its place — three things wrong with the panel were
 * visible here and in no test: a warning pill that called a 23,000-character
 * article 正文偏薄, a failure that spoke English, and a failed row that could
 * not say which page it was.
 */
import { createRoot } from "react-dom/client";
import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";
import type { AuthProvider } from "@workbench/auth/provider";
import { Panel } from "./Panel";
import "./panel.css";

const params = new URLSearchParams(location.search);
const pageUrl = params.get("url") ?? "https://www.rfc-editor.org/rfc/rfc2324.html";
const pageTitle = params.get("title") ?? "Hyper Text Coffee Pot Control Protocol";

const store = new Map<string, unknown>();
for (const [k, v] of Object.entries(localStorage)) {
  if (k.startsWith("liyan.")) store.set(k, v);
}
const persist = () => {
  for (const [k, v] of store) localStorage.setItem(k, String(v));
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith("liyan.") && !store.has(k)) localStorage.removeItem(k);
  }
};

(globalThis as unknown as { chrome: unknown }).chrome = {
  storage: {
    local: {
      get: async (key: string) =>
        store.has(key) ? { [key]: store.get(key) } : ({} as Record<string, unknown>),
      set: async (entries: Record<string, unknown>) => {
        for (const [k, v] of Object.entries(entries)) store.set(k, v);
        persist();
      },
      remove: async (key: string) => {
        store.delete(key);
        persist();
      },
    },
  },
  tabs: {
    query: async () => [{ url: pageUrl, title: pageTitle }],
    create: async ({ url }: { url: string }) => {
      (document.getElementById("opened") ?? document.body).setAttribute("data-opened", url);
      console.log("chrome.tabs.create", url);
    },
  },
};

// `?signedout=1` withholds the token, which is the only way to reach the
// sign-in screens here — including the resume, which is what the popup being
// destroyed mid-sign-in actually looks like.
const signedOut = params.get("signedout") === "1";

const authProvider: AuthProvider = {
  getAccessToken: async () => (signedOut ? null : "allowed-token"),
  sendEmailOtp: async () => undefined,
  verifyEmailOtp: async () => "allowed-token",
  signOut: async () => undefined,
  onAuthStateChange: () => () => undefined,
};

document.documentElement.dataset.theme = "system";
createRoot(document.getElementById("root")!).render(
  <InterfaceLocaleProvider locale="zh">
    <Panel authProvider={authProvider} />
  </InterfaceLocaleProvider>,
);

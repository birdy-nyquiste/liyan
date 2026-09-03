import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Languages, MonitorCog, MoonStar, Sun } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";

import {
  ApiError,
  loadTaskWorkspace,
  onSessionExpired,
  serverIsAlive,
  type AccessToken,
} from "./api/client";
import { type AuthProvider, supabaseAuthProvider } from "./auth/provider";
import type { AuthViewState, SignedOutState } from "./auth/state";
import { AuthPanel } from "./components/AuthPanel";
import { AppShell } from "./components/AppShell";
import { InterfaceLocaleProvider, type InterfaceLocale } from "./interfaceLocale";
import { installHistoryGuard } from "./navigationGuard";
import "./styles.css";

type HealthState = "checking" | "available" | "unavailable";
type Theme = "light" | "dark" | "system";

const THEME_LABEL = {
  zh: { name: "主题", light: "浅色", dark: "深色", system: "跟随系统" },
  en: { name: "Theme", light: "Light", dark: "Dark", system: "System" },
} as const;
type AppProps = { authProvider?: AuthProvider };
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000 } } });

const signedOut = (message: string | null = null): SignedOutState => ({
  screen: "email",
  email: "",
  busy: false,
  message,
});

/**
 * What a writer is told when their login ran out under them.
 *
 * Worth saying rather than dropping them at a blank form: they were in the
 * middle of something, and the form on its own reads as the workbench having
 * forgotten them.
 */
const SESSION_EXPIRED = "登录已过期，请重新登录。";

function AppWorkspace({ authProvider = supabaseAuthProvider }: AppProps) {
  const [health, setHealth] = useState<HealthState>("checking");
  const [auth, setAuth] = useState<AuthViewState>({ screen: "checking" });
  /** Set while the writer's own sign-out is in flight. See the expiry effect. */
  const signingOut = useRef(false);

  /**
   * The token to sign the next request with, asked for at the moment it is
   * needed rather than read once and kept.
   *
   * This one function is what every request in the workbench ends up calling,
   * because it is what gets threaded down as `accessToken`. A provider that
   * cannot answer is the same situation as a session that has ended, so it
   * takes the same path: no token, and the request is refused as 401.
   */
  const accessToken = useMemo<AccessToken>(
    () => () => authProvider.getAccessToken().catch(() => null),
    [authProvider],
  );

  const openWorkspace = useCallback(
    async () => {
      setAuth((current) =>
        current.screen === "email" || current.screen === "otp"
          ? { ...current, busy: true, message: null }
          : { screen: "checking" },
      );
      try {
        const workspace = await loadTaskWorkspace(accessToken);
        setAuth({
          screen: "workspace",
          identity: workspace.identity,
          tasks: workspace.tasks,
          accessToken,
        });
      } catch (error) {
        const accessDenied = error instanceof ApiError && [401, 403].includes(error.status);
        if (accessDenied) await authProvider.signOut().catch(() => undefined);
        setAuth(
          signedOut(
            error instanceof ApiError && error.status === 403
              ? "此账号暂无访问权限。"
              : "暂时无法进入工作台，请稍后重试。",
          ),
        );
      }
    },
    [accessToken, authProvider],
  );

  useEffect(() => {
    let active = true;
    void serverIsAlive()
      .then((isAlive) => {
        if (active) setHealth(isAlive ? "available" : "unavailable");
      })
      .catch(() => {
        if (active) setHealth("unavailable");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    void authProvider
      .getAccessToken()
      .then((token) => {
        if (!active) return;
        if (token) void openWorkspace();
        else setAuth(signedOut());
      })
      .catch(() => {
        if (active) setAuth(signedOut());
      });
    return () => {
      active = false;
    };
  }, [authProvider, openWorkspace]);

  /**
   * Return to sign-in when the session ends, however the workbench finds out.
   *
   * Two things can tell it. Supabase says so directly when a session can no
   * longer be refreshed, which is the ordinary case — a tab left open past the
   * refresh token's life. The server says so as a 401 on some request, which
   * covers everything Supabase cannot know about, an account removed
   * mid-session among them.
   *
   * Both are ignored unless a workbench is actually on screen. A writer who
   * has just signed out themselves is already where this would send them, and
   * telling them their login expired would be a lie about what they just did.
   */
  useEffect(() => {
    if (auth.screen !== "workspace") return;
    const expire = () =>
      setAuth((current) => {
        // A writer who has just signed out themselves is already where this
        // would send them, and telling them their login expired would be a lie
        // about what they just did. Supabase announces a deliberate sign-out
        // through this same listener, and announces it *during* `signOut`,
        // before the screen has changed — so the screen alone cannot tell the
        // two apart and `signingOut` is what does.
        if (signingOut.current || current.screen !== "workspace") return current;
        queryClient.clear();
        return signedOut(SESSION_EXPIRED);
      });
    const stopWatchingSession = authProvider.onAuthStateChange((token) => {
      if (!token) expire();
    });
    const stopWatchingRefusals = onSessionExpired(expire);
    return () => {
      stopWatchingSession();
      stopWatchingRefusals();
    };
  }, [auth.screen, authProvider]);

  async function requestOtp(email: string) {
    // A resend is this same call from the 验证码 screen, and it must not throw the
    // writer back to the address form while it is in flight.
    setAuth((current) =>
      current.screen === "otp"
        ? { ...current, busy: true, message: null }
        : { screen: "email", email, busy: true, message: null },
    );
    try {
      await authProvider.sendEmailOtp(email.trim());
      setAuth({ screen: "otp", email, otp: "", busy: false, message: null });
    } catch {
      setAuth((current) => ({
        ...(current.screen === "otp" ? current : { screen: "email" as const, email }),
        busy: false,
        message: "验证码发送失败，请稍后重试。",
      }));
    }
  }

  async function verifyOtp(email: string, otp: string) {
    setAuth({ screen: "otp", email, otp, busy: true, message: null });
    try {
      await authProvider.verifyEmailOtp(email.trim(), otp.trim());
      await openWorkspace();
    } catch {
      setAuth({
        screen: "otp",
        email,
        otp,
        busy: false,
        message: "验证码无效或已过期。",
      });
    }
  }

  // The workbench lets a writer choose the interface language and theme; before
  // sign-in they could only inherit those choices, never make them. Both are
  // stored under the keys AppShell reads, so a choice made here survives into
  // the workbench.
  const [signedOutLocale, setSignedOutLocale] = useState<InterfaceLocale>(() =>
    window.localStorage.getItem("liyan.locale") === "en" ? "en" : "zh",
  );
  const [signedOutTheme, setSignedOutTheme] = useState<Theme>(() => {
    const stored = window.localStorage.getItem("liyan.theme");
    return stored === "dark" || stored === "system" ? stored : "light";
  });

  useEffect(() => {
    if (auth.screen === "workspace") return;
    window.localStorage.setItem("liyan.locale", signedOutLocale);
    document.documentElement.lang = signedOutLocale === "zh" ? "zh-CN" : "en";
  }, [auth.screen, signedOutLocale]);

  useEffect(() => {
    if (auth.screen === "workspace") return;
    window.localStorage.setItem("liyan.theme", signedOutTheme);
    document.documentElement.dataset.theme = signedOutTheme;
  }, [auth.screen, signedOutTheme]);

  const content = auth.screen === "workspace" ? (
    <AppShell
      identity={auth.identity}
      accessToken={auth.accessToken}
      initialTasks={auth.tasks}
      serviceUnavailable={health === "unavailable"}
      onSignOut={async () => {
        signingOut.current = true;
        try {
          await authProvider.signOut();
          queryClient.clear();
          setAuth(signedOut());
        } finally {
          signingOut.current = false;
        }
      }}
    />
  ) : auth.screen === "checking" ? null : (
    <main className={`signed-out-shell${health === "unavailable" ? " signed-out-shell--degraded" : ""}`}>
      <div className="signed-out-topbar">
        {health === "unavailable" ? <div className="service-banner" role="alert">{signedOutLocale === "en" ? "The service is temporarily unavailable. Some actions may fail." : "服务暂不可用，部分操作可能失败。"}</div> : null}
        {/* Both pills name their setting's current value, the way the workbench's
            own preference rows do. */}
        <div className="signed-out-preferences">
          <button
            className="signed-out-pill"
            type="button"
            aria-label={`${THEME_LABEL[signedOutLocale].name}: ${THEME_LABEL[signedOutLocale][signedOutTheme]}`}
            onClick={() =>
              setSignedOutTheme(
                signedOutTheme === "light" ? "dark" : signedOutTheme === "dark" ? "system" : "light",
              )
            }
          >
            {signedOutTheme === "light" ? <Sun size={16} aria-hidden="true" />
              : signedOutTheme === "dark" ? <MoonStar size={16} aria-hidden="true" />
              : <MonitorCog size={16} aria-hidden="true" />}
            <span>{THEME_LABEL[signedOutLocale][signedOutTheme]}</span>
          </button>
          <button
            className="signed-out-pill"
            type="button"
            aria-label={`${signedOutLocale === "en" ? "Language" : "语言"}: ${signedOutLocale === "en" ? "English" : "中文"}`}
            onClick={() => setSignedOutLocale(signedOutLocale === "en" ? "zh" : "en")}
          >
            <Languages size={16} aria-hidden="true" />
            <span>{signedOutLocale === "en" ? "English" : "中文"}</span>
          </button>
        </div>
      </div>
      <header className="signed-out-hero">
        <div className="masthead__brand">
          <img className="masthead__mark" src="/liyan-mark.svg" alt="" />
          <div>
            <h1>立言阁</h1>
            <p className="subtitle">{signedOutLocale === "en" ? "Write from insight, stand through understanding" : "有感而发，知言而立"}</p>
          </div>
        </div>
      </header>
      <AuthPanel
        state={auth}
        onEmailChange={(email) => setAuth({ ...auth, email })}
        onOtpChange={(otp) => { if (auth.screen === "otp") setAuth({ ...auth, otp }); }}
        onRequestOtp={requestOtp}
        onVerifyOtp={verifyOtp}
        onRestartEmail={() =>
          // Prefilled, because the reason to come back here is a typo in it.
          setAuth({ screen: "email", email: auth.email, busy: false, message: null })
        }
      />
    </main>
  );

  return <InterfaceLocaleProvider locale={signedOutLocale}>{content}</InterfaceLocaleProvider>;
}

export default function App({ authProvider = supabaseAuthProvider }: AppProps) {
  const router = useMemo(() => {
    installHistoryGuard();
    return createBrowserRouter([
      { path: "*", element: <AppWorkspace authProvider={authProvider} /> },
    ]);
  }, [authProvider]);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
  );
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createBrowserRouter, RouterProvider, useLocation } from "react-router-dom";
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
import { PublicSite } from "./public/PublicSite";
import "./styles.css";

type HealthState = "checking" | "available" | "unavailable";
type Theme = "light" | "dark" | "system";

type AppProps = { authProvider?: AuthProvider };
/** How often the workbench re-probes a server that did not answer. */
const HEALTH_RECHECK_MS = 5_000;

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
  const location = useLocation();
  const publicPage = ["/", "/terms", "/privacy"].includes(location.pathname);
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

  /**
   * Watch whether the server answers, until it does.
   *
   * One failed probe is usually not a service that is down. It is a page that
   * loaded while the server was still waking, or a single flaky request. A
   * one-shot check turns that instant into a banner that stays up for the rest
   * of the session: every action the writer takes succeeds while the top of the
   * screen still says the service is unavailable, and only a reload clears it.
   * So the probe repeats while the answer is bad and stops once it is good —
   * the banner is allowed to go away by itself, the way the outage does.
   *
   * Probes overlap, and their answers do not come back in the order they were
   * asked for. A server that is restarting holds a request open instead of
   * refusing it, so a probe sent during the outage is still hanging when a
   * later one gets a clean answer, and then lands as its own 5s deadline —
   * describing a moment that has already passed. Taken at face value it put
   * the banner back up over a service that was answering fine, and by then the
   * watch had stopped, so nothing was left to take it down again: a reload was
   * the only cure. Hence `answered`. An answer older than the one on screen is
   * not news about the server, and is dropped.
   */
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    /** Probes asked for, and the newest one whose answer reached the screen. */
    let asked = 0;
    let answered = 0;

    const probe = () => {
      const mine = ++asked;
      // 只有比屏幕上那个答案更新的答案才算新消息 —— 一次挂了很久才到期的旧探测
      // 说的是已经过去的那次停机，不该把横幅重新拉起来。
      const isStale = () => !active || mine < answered;
      void serverIsAlive()
        .then((isAlive) => {
          if (isStale()) return;
          answered = mine;
          setHealth(isAlive ? "available" : "unavailable");
          if (isAlive) stopWatching();
        })
        .catch(() => {
          if (isStale()) return;
          answered = mine;
          setHealth("unavailable");
        });
    };

    const stopWatching = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
      window.removeEventListener("online", probe);
      window.removeEventListener("focus", probe);
    };

    probe();
    timer = setInterval(probe, HEALTH_RECHECK_MS);
    // 网络恢复或写作者回到这个标签页时立刻再探一次，而不是等下一个周期 —
    // 这两件事正是"刚才那次失败已经过时了"最强的信号。
    window.addEventListener("online", probe);
    window.addEventListener("focus", probe);

    return () => {
      active = false;
      stopWatching();
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

  // A session created in another tab must also update the public-page CTA.
  // Defer API work outside the auth provider's notification callback.
  useEffect(() => {
    if (!publicPage) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = authProvider.onAuthStateChange((token) => {
      if (timer) clearTimeout(timer);
      if (token) timer = setTimeout(() => void openWorkspace(), 0);
      else setAuth(signedOut());
    });
    return () => { stop(); if (timer) clearTimeout(timer); };
  }, [authProvider, openWorkspace, publicPage]);

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
    if (auth.screen === "workspace" && !publicPage) return;
    window.localStorage.setItem("liyan.locale", signedOutLocale);
    document.documentElement.lang = signedOutLocale === "zh" ? "zh-CN" : "en";
  }, [auth.screen, signedOutLocale, publicPage]);

  useEffect(() => {
    if (auth.screen === "workspace" && !publicPage) return;
    window.localStorage.setItem("liyan.theme", signedOutTheme);
    document.documentElement.dataset.theme = signedOutTheme;
  }, [auth.screen, signedOutTheme, publicPage]);

  // Hash navigation also works from the legal and sign-in pages. Native anchor
  // scrolling alone does not handle a target mounted by client-side routing.
  useEffect(() => {
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
    else window.scrollTo?.(0, 0);
  }, [location.pathname, location.hash]);

  const publicProps = {
    locale: signedOutLocale,
    mode: signedOutTheme,
    onLocaleChange: () => setSignedOutLocale(signedOutLocale === "en" ? "zh" : "en"),
    onModeChange: () => setSignedOutTheme(signedOutTheme === "light" ? "dark" : signedOutTheme === "dark" ? "system" : "light"),
    signedIn: auth.screen === "workspace",
    checking: auth.screen === "checking",
  };
  const content = publicPage ? <PublicSite {...publicProps} /> : auth.screen === "workspace" ? (
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
  ) : auth.screen === "checking" ? <PublicSite {...publicProps}><p role="status">{signedOutLocale === "en" ? "Loading…" : "读取中…"}</p></PublicSite> : (
    <PublicSite {...publicProps}>
      {health === "unavailable" ? <div className="service-banner" role="alert">{signedOutLocale === "en" ? "The service is temporarily unavailable. Some actions may fail." : "服务暂不可用，部分操作可能失败。"}</div> : null}
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
    </PublicSite>
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

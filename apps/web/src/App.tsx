import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";

import { ApiError, loadTaskWorkspace, serverIsAlive } from "./api/client";
import { type AuthProvider, supabaseAuthProvider } from "./auth/provider";
import type { AuthViewState, SignedOutState } from "./auth/state";
import { AuthPanel } from "./components/AuthPanel";
import { AppShell } from "./components/AppShell";
import "./styles.css";

type HealthState = "checking" | "available" | "unavailable";
type AppProps = { authProvider?: AuthProvider };
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000 } } });

const signedOut = (message: string | null = null): SignedOutState => ({
  screen: "email",
  email: "",
  busy: false,
  message,
});

export default function App({ authProvider = supabaseAuthProvider }: AppProps) {
  const [health, setHealth] = useState<HealthState>("checking");
  const [auth, setAuth] = useState<AuthViewState>({ screen: "checking" });

  const openWorkspace = useCallback(
    async (accessToken: string) => {
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
    [authProvider],
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
      .then((accessToken) => {
        if (!active) return;
        if (accessToken) void openWorkspace(accessToken);
        else setAuth(signedOut());
      })
      .catch(() => {
        if (active) setAuth(signedOut());
      });
    return () => {
      active = false;
    };
  }, [authProvider, openWorkspace]);

  async function requestOtp(email: string) {
    setAuth({ screen: "email", email, busy: true, message: null });
    try {
      await authProvider.sendEmailOtp(email.trim());
      setAuth({ screen: "otp", email, otp: "", busy: false, message: null });
    } catch {
      setAuth({
        screen: "email",
        email,
        busy: false,
        message: "验证码发送失败，请稍后重试。",
      });
    }
  }

  async function verifyOtp(email: string, otp: string) {
    setAuth({ screen: "otp", email, otp, busy: true, message: null });
    try {
      const accessToken = await authProvider.verifyEmailOtp(email.trim(), otp.trim());
      await openWorkspace(accessToken);
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

  const content = auth.screen === "workspace" ? (
    <AppShell
      identity={auth.identity}
      accessToken={auth.accessToken}
      initialTasks={auth.tasks}
      onSignOut={async () => {
        await authProvider.signOut();
        queryClient.clear();
        setAuth(signedOut());
      }}
    />
  ) : auth.screen === "checking" ? null : (
    <main className="signed-out-shell">
      <header className="signed-out-hero">
        <div className="masthead__brand">
          <img className="masthead__mark" src="/liyan-mark.svg" alt="" />
          <div>
            <h1>立言阁</h1>
            <p className="subtitle">有感而发，知言而立</p>
            <p className="signed-out-hero__description">从来源中辨明事实与观点，再写成由你定调的文章。</p>
          </div>
        </div>
      </header>
      {health === "unavailable" ? <div className="service-banner" role="alert">服务暂不可用，部分操作可能失败。</div> : null}
      <AuthPanel
        state={auth}
        onEmailChange={(email) => setAuth({ ...auth, email })}
        onOtpChange={(otp) => { if (auth.screen === "otp") setAuth({ ...auth, otp }); }}
        onRequestOtp={requestOtp}
        onVerifyOtp={verifyOtp}
      />
    </main>
  );

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{content}</BrowserRouter>
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
  );
}

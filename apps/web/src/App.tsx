import { useCallback, useEffect, useState } from "react";

import { ApiError, loadTaskWorkspace, serverIsAlive } from "./api/client";
import { type AuthProvider, supabaseAuthProvider } from "./auth/provider";
import type { AuthViewState, SignedOutState } from "./auth/state";
import { AuthPanel } from "./components/AuthPanel";
import { TaskWorkspace } from "./components/TaskWorkspace";
import "./styles.css";

type HealthState = "checking" | "available" | "unavailable";
type AppProps = { authProvider?: AuthProvider };

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

  return (
    <main className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">LIYAN WORKBENCH</p>
          <h1>立言阁</h1>
          <p className="subtitle">从来源到知言，再到由你定调的立言文章。</p>
        </div>
        <div className={`status status--${health}`} role="status" aria-live="polite">
          <span className="status__dot" aria-hidden="true" />
          <span>
            {health === "checking" && "正在检查服务"}
            {health === "available" && "服务正常"}
            {health === "unavailable" && "服务暂不可用"}
          </span>
        </div>
      </header>

      {auth.screen === "workspace" ? (
        <TaskWorkspace
          identity={auth.identity}
          accessToken={auth.accessToken}
          tasks={auth.tasks}
          onTaskCreated={(task) =>
            setAuth((current) =>
              current.screen === "workspace"
                ? { ...current, tasks: [task, ...current.tasks] }
                : current,
            )
          }
          onTaskDeleted={(taskId) =>
            setAuth((current) =>
              current.screen === "workspace"
                ? { ...current, tasks: current.tasks.filter((task) => task.id !== taskId) }
                : current,
            )
          }
          onTasksChanged={(tasks) =>
            setAuth((current) =>
              current.screen === "workspace" ? { ...current, tasks } : current,
            )
          }
          onSignOut={async () => {
            await authProvider.signOut();
            setAuth(signedOut());
          }}
        />
      ) : auth.screen === "checking" ? null : (
        <AuthPanel
          state={auth}
          onEmailChange={(email) => setAuth({ ...auth, email })}
          onOtpChange={(otp) => {
            if (auth.screen === "otp") setAuth({ ...auth, otp });
          }}
          onRequestOtp={requestOtp}
          onVerifyOtp={verifyOtp}
        />
      )}
    </main>
  );
}

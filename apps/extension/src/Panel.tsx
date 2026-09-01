import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, type AccessToken, getAccount } from "@workbench/api/client";
import type { AuthProvider } from "@workbench/auth/provider";
import type { SignedOutState } from "@workbench/auth/state";
import { AuthPanel } from "@workbench/components/AuthPanel";

import { extensionAuthProvider } from "./authProvider";

/**
 * What the panel is showing.
 *
 * `checking` is the opening frame, and it is deliberately not the sign-in
 * screen: the session usually survives, and starting at 登录 would flash a form
 * at a user who is already signed in every single time they open the panel.
 */
type PanelState =
  | { screen: "checking" }
  | SignedOutState
  | { screen: "ready"; isPayingUser: boolean };

const SESSION_EXPIRED = "登录已过期，请重新登录。";
const ACCESS_DENIED = "此账号暂无访问权限。";
const UNAVAILABLE = "暂时无法连接立言阁，请稍后重试。";

function signedOut(message: string | null = null): SignedOutState {
  return { screen: "email", email: "", busy: false, message };
}

export function Panel({ authProvider = extensionAuthProvider }: { authProvider?: AuthProvider }) {
  const [state, setState] = useState<PanelState>({ screen: "checking" });

  /**
   * The token to send, fetched per request rather than held.
   *
   * The workbench does this because a tab left open outlives an access token.
   * The panel has the same need for a different reason: it is destroyed and
   * rebuilt constantly, so anything it caches is worthless, and the one thing
   * that must not be cached is a token that may have expired between openings.
   */
  const accessToken = useMemo<AccessToken>(
    () => () => authProvider.getAccessToken().catch(() => null),
    [authProvider],
  );

  const enter = useCallback(async () => {
    setState((current) =>
      current.screen === "email" || current.screen === "otp"
        ? { ...current, busy: true, message: null }
        : { screen: "checking" },
    );
    try {
      const account = await getAccount(accessToken);
      setState({ screen: "ready", isPayingUser: account.is_paying_user });
    } catch (error) {
      // 401 and 403 both mean this session cannot be used, so it is discarded
      // rather than left to fail the same way on the next opening. They are
      // told apart only in what the user is told: one is a session that ended,
      // the other an account 立言阁 does not admit, and offering "log in again"
      // to the second would send them around a loop that cannot end.
      const refused = error instanceof ApiError && [401, 403].includes(error.status);
      if (refused) await authProvider.signOut().catch(() => undefined);
      setState(
        signedOut(
          error instanceof ApiError && error.status === 403
            ? ACCESS_DENIED
            : error instanceof ApiError && error.status === 401
              ? SESSION_EXPIRED
              : UNAVAILABLE,
        ),
      );
    }
  }, [accessToken, authProvider]);

  useEffect(() => {
    let active = true;
    void authProvider
      .getAccessToken()
      .then((token) => {
        if (!active) return;
        if (token) void enter();
        else setState(signedOut());
      })
      .catch(() => {
        if (active) setState(signedOut());
      });
    return () => {
      active = false;
    };
  }, [authProvider, enter]);

  async function requestOtp(email: string) {
    // A resend is this same call from the 验证码 screen, and it must not throw
    // the user back to the address form while it is in flight.
    setState((current) =>
      current.screen === "otp"
        ? { ...current, busy: true, message: null }
        : { screen: "email", email, busy: true, message: null },
    );
    try {
      await authProvider.sendEmailOtp(email.trim());
      setState({ screen: "otp", email, otp: "", busy: false, message: null });
    } catch {
      setState((current) => ({
        ...(current.screen === "otp" ? current : { screen: "email" as const, email }),
        busy: false,
        message: "验证码发送失败，请稍后重试。",
      }));
    }
  }

  async function verifyOtp(email: string, otp: string) {
    setState({ screen: "otp", email, otp, busy: true, message: null });
    try {
      await authProvider.verifyEmailOtp(email.trim(), otp.trim());
      await enter();
    } catch {
      setState({ screen: "otp", email, otp, busy: false, message: "验证码无效或已过期。" });
    }
  }

  return (
    <div className="panel">
      <header className="panel__head">
        <span className="panel__mark" aria-hidden="true">
          立
        </span>
        <span className="panel__name">立言阁</span>
      </header>
      <Body
        state={state}
        onEmailChange={(email) =>
          setState((current) => (current.screen === "email" ? { ...current, email } : current))
        }
        onOtpChange={(otp) =>
          setState((current) => (current.screen === "otp" ? { ...current, otp } : current))
        }
        onRequestOtp={requestOtp}
        onVerifyOtp={verifyOtp}
        onRestartEmail={() => setState(signedOut())}
      />
    </div>
  );
}

type BodyProps = {
  state: PanelState;
  onEmailChange(email: string): void;
  onOtpChange(otp: string): void;
  onRequestOtp(email: string): Promise<void>;
  onVerifyOtp(email: string, otp: string): Promise<void>;
  onRestartEmail(): void;
};

function Body({ state, ...handlers }: BodyProps): ReactNode {
  if (state.screen === "checking") {
    return (
      <div className="panel__body">
        <p className="form-status" role="status">
          读取中…
        </p>
      </div>
    );
  }

  if (state.screen === "ready") {
    // 主屏 and the 付费用户 gate arrive with the basket; until then this says
    // plainly that sign-in worked and nothing else is built yet.
    return (
      <div className="panel__body">
        <p className="form-hint">已登录。收集来源的功能还在开发中。</p>
      </div>
    );
  }

  return (
    <div className="panel__body">
      <AuthPanel state={state} {...handlers} />
    </div>
  );
}

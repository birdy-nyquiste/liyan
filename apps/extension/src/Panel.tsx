import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, type AccessToken, getAccount } from "@workbench/api/client";
import { PAID_ONLY } from "@workbench/components/creditRefusal";
import type { AuthProvider } from "@workbench/auth/provider";
import type { SignedOutState } from "@workbench/auth/state";
import { AuthPanel } from "@workbench/components/AuthPanel";

import { extensionAuthProvider } from "./authProvider";
import { Basket } from "./Basket";
import { openBasket, readBasketId } from "./basketId";
import { openWorkbench } from "./workbench";

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
  /** Signed in, but URL 来源 are what a 付费用户 buys and this user has not. */
  | { screen: "locked" }
  /** Signed in and able to collect, with no basket open. */
  | { screen: "home" }
  /** A basket is open. Filling it belongs to the next issue. */
  | { screen: "basket"; basketId: string };

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
      // Asked before anything is drawn, and both answers are drawn from it.
      // A user who cannot capture is shown why, rather than a 新建任务 button
      // whose only possible outcome is a refusal — which, for a newly
      // installed 插件, would be the very first thing it ever did.
      const [account, basketId] = await Promise.all([getAccount(accessToken), readBasketId()]);
      if (!account.is_paying_user) setState({ screen: "locked" });
      else if (basketId) setState({ screen: "basket", basketId });
      else setState({ screen: "home" });
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
        accessToken={accessToken}
        onOpenBasket={async () => setState({ screen: "basket", basketId: await openBasket() })}
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
  accessToken: AccessToken;
  onOpenBasket(): Promise<void>;
  onEmailChange(email: string): void;
  onOtpChange(otp: string): void;
  onRequestOtp(email: string): Promise<void>;
  onVerifyOtp(email: string, otp: string): Promise<void>;
  onRestartEmail(): void;
};

function Body({ state, accessToken, onOpenBasket, ...handlers }: BodyProps): ReactNode {
  if (state.screen === "checking") {
    return (
      <div className="panel__body">
        <p className="form-status" role="status">
          读取中…
        </p>
      </div>
    );
  }

  if (state.screen === "locked") {
    // The server's own sentence, not a paraphrase of it: `creditRefusal.ts`
    // owns this string because the same refusal appears in 工作台, and two
    // wordings for one rule is how they drift apart.
    return (
      <div className="panel__body">
        <p className="form-error" role="alert">
          {PAID_ONLY}
        </p>
        <button className="button" type="button" onClick={() => void openWorkbench("/account")}>
          前往工作台购买额度
        </button>
        <p className="form-hint">购买后回到这里，就能开始新建任务。</p>
      </div>
    );
  }

  if (state.screen === "home") {
    return (
      <div className="panel__body">
        <p className="form-hint">把浏览中读到的页面收集成来源，最多三条，一起建成一个立言任务。</p>
        <button className="button" type="button" onClick={() => void onOpenBasket()}>
          新建任务
        </button>
      </div>
    );
  }

  if (state.screen === "basket") {
    return <Basket accessToken={accessToken} basketId={state.basketId} />;
  }

  return (
    <div className="panel__body">
      <AuthPanel state={state} {...handlers} />
    </div>
  );
}

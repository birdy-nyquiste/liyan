import { type FormEvent, useState } from "react";

import type { SignedOutState } from "../auth/state";
import { useInterfaceLocale } from "../interfaceLocale";
import { useFocusWhen } from "./useFocusWhen";

type AuthPanelProps = {
  state: SignedOutState;
  onEmailChange(email: string): void;
  onOtpChange(otp: string): void;
  onRequestOtp(email: string): Promise<void>;
  onVerifyOtp(email: string, otp: string): Promise<void>;
  onRestartEmail(): void;
  /**
   * Where 使用条款 and 隐私政策 answer, for clients that are not 工作台.
   *
   * The workbench serves both itself, so it passes nothing and the links stay
   * relative. The 插件 has to pass its 工作台's address: a relative `/terms`
   * inside a popup resolves to `chrome-extension://<id>/terms`, which is a page
   * that does not exist — and the one place a user is agreeing to those
   * documents is the worst place to hand them a broken link.
   */
  legalBaseUrl?: string;
};

export function AuthPanel({
  state,
  onEmailChange,
  onOtpChange,
  onRequestOtp,
  onVerifyOtp,
  onRestartEmail,
  legalBaseUrl,
}: AuthPanelProps) {
  const { locale, t } = useInterfaceLocale();
  // A resend is the same request as the first send; only the reassurance differs,
  // and it is local to this panel because nothing outside it changes.
  const [resent, setResent] = useState(false);
  const emailField = useFocusWhen<HTMLInputElement>(state.screen === "email");
  const otpField = useFocusWhen<HTMLInputElement>(state.screen === "otp");

  function submitEmail(event: FormEvent) {
    event.preventDefault();
    void onRequestOtp(state.email);
  }

  function submitOtp(event: FormEvent) {
    event.preventDefault();
    if (state.screen === "otp") void onVerifyOtp(state.email, state.otp);
  }

  function resendOtp() {
    setResent(false);
    void onRequestOtp(state.email).then(() => {
      setResent(true);
      // The field was cleared by the new code; put the caret back in it rather
      // than leaving focus on a button that has done its job.
      otpField.current?.focus();
    });
  }

  /** A legal document's address, absolute only where it has to be. */
  const legal = (path: string) => (legalBaseUrl ? new URL(path, legalBaseUrl).toString() : path);

  const describedBy = [state.screen === "otp" ? "auth-sent" : null, state.message ? "auth-error" : null]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="workspace auth-card" aria-labelledby="auth-heading">
      <div>
        <h2 id="auth-heading">{t("登入立言阁")}</h2>
        <p className="auth-card__lede">
          {t("使用邮箱接收一次性验证码，无需密码。首次登入自动创建账号。")}
        </p>
      </div>

      {state.screen === "email" ? (
        <form className="auth-form" onSubmit={submitEmail}>
          <label htmlFor="email">{t("邮箱")}</label>
          <input
            id="email"
            ref={emailField}
            type="email"
            inputMode="email"
            autoComplete="email"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            aria-describedby={describedBy || undefined}
            value={state.email}
            onChange={(event) => onEmailChange(event.target.value)}
          />
          <button className="button" type="submit" disabled={state.busy} aria-busy={state.busy}>
            {state.busy ? t("发送中…") : t("发送验证码")}
          </button>
        </form>
      ) : (
        <form className="auth-form" onSubmit={submitOtp}>
          <p className="form-hint" id="auth-sent">
            {locale === "en"
              ? `Verification code sent to ${state.email}`
              : `验证码已发送至 ${state.email}`}
          </p>
          <label htmlFor="otp">{t("验证码")}</label>
          <input
            id="otp"
            ref={otpField}
            className="auth-form__code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]*"
            maxLength={6}
            required
            aria-describedby={describedBy || undefined}
            value={state.otp}
            onChange={(event) => onOtpChange(event.target.value)}
          />
          <button className="button" type="submit" disabled={state.busy} aria-busy={state.busy}>
            {state.busy ? t("登录中…") : t("登录")}
          </button>
          {/* A mistyped address is the common failure here, and reloading the page
              was the only way back to it. */}
          <div className="auth-form__alternatives">
            <button className="button button--quiet" type="button" onClick={onRestartEmail}>
              {t("换个邮箱")}
            </button>
            <button
              className="button button--quiet"
              type="button"
              onClick={resendOtp}
              disabled={state.busy}
            >
              {t("重新发送")}
            </button>
          </div>
        </form>
      )}
      <p className="form-status" role="status">
        {resent && state.screen === "otp" && !state.message ? t("验证码已重新发送。") : null}
      </p>
      {state.message ? (
        <p className="form-error" id="auth-error" role="alert">
          {t(state.message)}
        </p>
      ) : null}
      {/* Both screens, and at the foot of the card rather than under the button,
          so that a refusal is never pushed below a line of small print. Opened
          in a tab of their own: reading the 条款 must not cost the address
          already typed into the field above — and in the 插件, where the popup
          is destroyed by any navigation, that is not a nicety. */}
      <p className="auth-card__legal">
        {locale === "en" ? (
          <>
            By continuing, you agree to our{" "}
            <a href={legal("/terms")} target="_blank" rel="noreferrer">
              Terms of Use
            </a>{" "}
            and{" "}
            <a href={legal("/privacy")} target="_blank" rel="noreferrer">
              Privacy Policy
            </a>
            .
          </>
        ) : (
          <>
            继续即表示你同意我们的
            <a href={legal("/terms")} target="_blank" rel="noreferrer">
              《使用条款》
            </a>
            与
            <a href={legal("/privacy")} target="_blank" rel="noreferrer">
              《隐私政策》
            </a>
            。
          </>
        )}
      </p>
    </section>
  );
}

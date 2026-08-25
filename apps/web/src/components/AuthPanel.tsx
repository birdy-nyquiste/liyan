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
};

export function AuthPanel({
  state,
  onEmailChange,
  onOtpChange,
  onRequestOtp,
  onVerifyOtp,
  onRestartEmail,
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

  const describedBy = [state.screen === "otp" ? "auth-sent" : null, state.message ? "auth-error" : null]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="workspace auth-card" aria-labelledby="auth-heading">
      <div>
        <p className="section-kicker">{t("仅限受邀用户")}</p>
        <h2 id="auth-heading">{t("登录工作台")}</h2>
        <p className="auth-card__lede">{t("使用邮箱接收一次性验证码，无需密码。")}</p>
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
    </section>
  );
}

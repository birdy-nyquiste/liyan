import type { FormEvent } from "react";

import type { SignedOutState } from "../auth/state";

type AuthPanelProps = {
  state: SignedOutState;
  onEmailChange(email: string): void;
  onOtpChange(otp: string): void;
  onRequestOtp(email: string): Promise<void>;
  onVerifyOtp(email: string, otp: string): Promise<void>;
};

export function AuthPanel({
  state,
  onEmailChange,
  onOtpChange,
  onRequestOtp,
  onVerifyOtp,
}: AuthPanelProps) {
  function submitEmail(event: FormEvent) {
    event.preventDefault();
    void onRequestOtp(state.email);
  }

  function submitOtp(event: FormEvent) {
    event.preventDefault();
    if (state.screen === "otp") void onVerifyOtp(state.email, state.otp);
  }

  return (
    <section className="workspace auth-card" aria-labelledby="auth-heading">
      <div>
        <p className="section-kicker">仅限受邀用户</p>
        <h2 id="auth-heading">登录工作台</h2>
        <p>使用邮箱接收一次性验证码，无需密码。</p>
      </div>

      {state.screen === "email" ? (
        <form className="auth-form" onSubmit={submitEmail}>
          <label htmlFor="email">邮箱</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={state.email}
            onChange={(event) => onEmailChange(event.target.value)}
          />
          <button className="button" type="submit" disabled={state.busy}>
            发送验证码
          </button>
        </form>
      ) : (
        <form className="auth-form" onSubmit={submitOtp}>
          <p className="form-hint">验证码已发送至 {state.email}</p>
          <label htmlFor="otp">验证码</label>
          <input
            id="otp"
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            value={state.otp}
            onChange={(event) => onOtpChange(event.target.value)}
          />
          <button className="button" type="submit" disabled={state.busy}>
            登录
          </button>
        </form>
      )}
      {state.message ? (
        <p className="form-error" role="alert">
          {state.message}
        </p>
      ) : null}
    </section>
  );
}

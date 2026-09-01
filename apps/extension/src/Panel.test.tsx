import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@workbench/api/client";
import type { AuthProvider } from "@workbench/auth/provider";
import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";

import { Panel } from "./Panel";

const getAccount = vi.hoisted(() => vi.fn());

vi.mock("@workbench/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@workbench/api/client")>()),
  getAccount,
}));

function fakeAuthProvider(overrides: Partial<AuthProvider> = {}): AuthProvider {
  return {
    getAccessToken: vi.fn(async () => null),
    sendEmailOtp: vi.fn(async () => undefined),
    verifyEmailOtp: vi.fn(async () => "a-token"),
    signOut: vi.fn(async () => undefined),
    onAuthStateChange: vi.fn(() => () => undefined),
    ...overrides,
  };
}

function renderPanel(authProvider: AuthProvider) {
  return render(
    <InterfaceLocaleProvider locale="zh">
      <Panel authProvider={authProvider} />
    </InterfaceLocaleProvider>,
  );
}

beforeEach(() => {
  getAccount.mockReset();
});

describe("opening the panel", () => {
  it("asks for an email when there is no session", async () => {
    renderPanel(fakeAuthProvider());
    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();
  });

  /**
   * The panel is destroyed and rebuilt every time it is opened, so a stored
   * session has to carry the user past sign-in without showing it. Flashing the
   * form at somebody already signed in would happen on every single opening.
   */
  it("goes straight past sign-in when the stored session still works", async () => {
    getAccount.mockResolvedValue({ is_paying_user: true });
    renderPanel(fakeAuthProvider({ getAccessToken: vi.fn(async () => "a-token") }));

    expect(await screen.findByText(/已登录/)).toBeInTheDocument();
    expect(screen.queryByLabelText("邮箱")).not.toBeInTheDocument();
  });

  /**
   * Supabase will happily sign in an address 立言阁 does not admit; only the
   * server knows. Offering "log in again" for that would be a loop with no end,
   * so the session is discarded and the reason is said plainly.
   */
  it("says an account has no access when the server refuses it", async () => {
    const authProvider = fakeAuthProvider({ getAccessToken: vi.fn(async () => "a-token") });
    getAccount.mockRejectedValue(new ApiError(403, "Access is not available for this account."));
    renderPanel(authProvider);

    expect(await screen.findByRole("alert")).toHaveTextContent("此账号暂无访问权限。");
    expect(authProvider.signOut).toHaveBeenCalled();
  });

  it("keeps a session when the failure is not about access", async () => {
    const authProvider = fakeAuthProvider({ getAccessToken: vi.fn(async () => "a-token") });
    getAccount.mockRejectedValue(new ApiError(503));
    renderPanel(authProvider);

    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法连接立言阁，请稍后重试。");
    expect(authProvider.signOut).not.toHaveBeenCalled();
  });
});

describe("signing in", () => {
  it("takes an address, then a code, and lands inside", async () => {
    const user = userEvent.setup();
    const authProvider = fakeAuthProvider();
    getAccount.mockResolvedValue({ is_paying_user: false });
    renderPanel(authProvider);

    await user.type(await screen.findByLabelText("邮箱"), "reader@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));

    await user.type(await screen.findByLabelText("验证码"), "418392");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText(/已登录/)).toBeInTheDocument();
    expect(authProvider.sendEmailOtp).toHaveBeenCalledWith("reader@example.com");
    expect(authProvider.verifyEmailOtp).toHaveBeenCalledWith("reader@example.com", "418392");
  });

  it("keeps the reader on the code screen when the code is wrong", async () => {
    const user = userEvent.setup();
    const authProvider = fakeAuthProvider({
      verifyEmailOtp: vi.fn(async () => {
        throw new Error("invalid");
      }),
    });
    renderPanel(authProvider);

    await user.type(await screen.findByLabelText("邮箱"), "reader@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.type(await screen.findByLabelText("验证码"), "000000");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("验证码无效或已过期。");
    expect(screen.getByLabelText("验证码")).toBeInTheDocument();
  });
});

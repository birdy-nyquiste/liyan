import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { AuthProvider } from "./auth/provider";

describe("server health", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("checks that the server is alive without promoting normal health", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "alive" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "立言阁" })).toBeInTheDocument();
    expect(screen.queryByText("服务正常")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        method: "GET",
        url: "http://localhost:8000/health/live",
      }),
    );
  });

  it("shows a safe unavailable state when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("服务暂不可用");
  });
});

describe("Email OTP sign in", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the authenticated user's empty task list after OTP verification", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn().mockResolvedValue("verified-access-token"),
      signOut: vi.fn().mockResolvedValue(undefined),
    };
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.url.endsWith("/health/live")) {
        return Response.json({ status: "alive" });
      }
      if (request.url.endsWith("/auth/me")) {
        return Response.json({ id: "local-user-1", email: "writer@example.com" });
      }
      if (request.url.endsWith("/tasks")) {
        return Response.json({ items: [] });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.type(await screen.findByLabelText("邮箱"), "writer@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.type(screen.getByLabelText("验证码"), "123456");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("heading", { name: "新建立言任务" })).toBeInTheDocument();
    expect(screen.getByText("还没有立言任务")).toBeInTheDocument();
    expect(authProvider.sendEmailOtp).toHaveBeenCalledWith("writer@example.com");
    expect(authProvider.verifyEmailOtp).toHaveBeenCalledWith(
      "writer@example.com",
      "123456",
    );
    const authenticatedRequests = fetch.mock.calls
      .map(([request]) => request as Request)
      .filter((request) => request.url.endsWith("/auth/me") || request.url.endsWith("/tasks"));
    expect(authenticatedRequests).toHaveLength(2);
    expect(authenticatedRequests[0]?.headers.get("Authorization")).toBe(
      "Bearer verified-access-token",
    );
  });

  it("shows a safe denial and clears the session for a non-allowlisted account", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn().mockResolvedValue("outsider-access-token"),
      signOut: vi.fn().mockResolvedValue(undefined),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (request: Request) => {
        if (request.url.endsWith("/health/live")) {
          return Response.json({ status: "alive" });
        }
        return Response.json(
          { detail: "Access is not available for this account." },
          { status: 403 },
        );
      }),
    );
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.type(await screen.findByLabelText("邮箱"), "outsider@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.type(screen.getByLabelText("验证码"), "123456");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("此账号暂无访问权限。");
    expect(authProvider.signOut).toHaveBeenCalledOnce();
    expect(screen.queryByText("writer@example.com")).not.toBeInTheDocument();
  });
});

describe("routed workbench shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
  });

  it("introduces signed-out visitors before the OTP form", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));

    render(<App authProvider={authProvider} />);

    expect(await screen.findByRole("heading", { name: "立言阁" })).toBeInTheDocument();
    expect(screen.getByText("有感而发，知言而立")).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.queryByText("服务正常")).not.toBeInTheDocument();
  });

  it("redirects a signed-in user to /task and keeps navigation in an app shell", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (request: Request) => {
        if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
        if (request.url.endsWith("/auth/me")) {
          return Response.json({ id: "user-1", email: "writer@example.com" });
        }
        if (request.url.includes("/tasks")) {
          return Response.json({ items: [], next_cursor: null });
        }
        return new Response(null, { status: 404 });
      }),
    );

    render(<App authProvider={authProvider} />);

    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "新建立言任务" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "发布" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/task");
  });
});

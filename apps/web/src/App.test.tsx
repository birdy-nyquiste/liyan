import { act, render, screen, waitFor, within } from "@testing-library/react";
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
    let session: string | null = null;
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockImplementation(async () => session),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn().mockImplementation(async () => {
        session = "verified-access-token";
        return session;
      }),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
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
    let session: string | null = null;
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockImplementation(async () => session),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn().mockImplementation(async () => {
        session = "outsider-access-token";
        return session;
      }),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
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
  it("returns to the address form with the address still in it", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.type(await screen.findByLabelText("邮箱"), "wrong@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.click(await screen.findByRole("button", { name: "换个邮箱" }));

    // The reason to come back here is a typo, so the address has to be editable
    // rather than retyped.
    expect(await screen.findByLabelText("邮箱")).toHaveValue("wrong@example.com");
  });

  it("sends a fresh code without leaving the 验证码 form", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn().mockResolvedValue(undefined),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.type(await screen.findByLabelText("邮箱"), "writer@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.type(await screen.findByLabelText("验证码"), "111111");
    await user.click(screen.getByRole("button", { name: "重新发送" }));

    expect(await screen.findByRole("status")).toHaveTextContent("验证码已重新发送。");
    // The old code stopped working the moment a new one was issued.
    expect(screen.getByLabelText("验证码")).toHaveValue("");
    expect(screen.getByLabelText("验证码")).toHaveFocus();
    expect(authProvider.sendEmailOtp).toHaveBeenCalledTimes(2);
  });

  it("keeps a signed-out visitor's language choice for the next visit", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    // The pill names the setting and its current value, as the workbench's own
    // preference rows do.
    await user.click(await screen.findByRole("button", { name: "语言: 中文" }));

    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Language: English" })).toBeInTheDocument();
    expect(window.localStorage.getItem("liyan.locale")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    window.localStorage.clear();
  });
});

describe("a session that outlives its access token", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
  });

  /** A workbench signed in with `first`, whose session later holds `second`. */
  function signedIn(session: { token: string | null }) {
    return {
      getAccessToken: vi.fn().mockImplementation(async () => session.token),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    } satisfies AuthProvider;
  }

  function workbenchFetch(respond?: (request: Request) => Response | undefined) {
    return vi.fn().mockImplementation(async (request: Request) => {
      const override = respond?.(request);
      if (override) return override;
      if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
      if (request.url.endsWith("/auth/me")) {
        return Response.json({ id: "user-1", email: "writer@example.com" });
      }
      if (request.url.includes("/tasks")) return Response.json({ items: [], next_cursor: null });
      if (request.url.includes("/publication/")) {
        return Response.json({ items: [], next_cursor: null });
      }
      return new Response(null, { status: 404 });
    });
  }

  it("signs each request with the session's current token, not sign-in's", async () => {
    // The bug this exists for: the token was read once and threaded through
    // every component, so an hour after sign-in the workbench was still
    // presenting the token it opened with and the server refused all of it.
    const session = { token: "token-at-sign-in" };
    const fetch = workbenchFetch();
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();

    render(<App authProvider={signedIn(session)} />);
    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();

    // What supabase-js does in the background once the first token expires.
    session.token = "token-after-refresh";
    await user.click(screen.getByRole("link", { name: "发布" }));
    expect(await screen.findByRole("heading", { name: "选择草稿" })).toBeInTheDocument();

    const publicationRequests = fetch.mock.calls
      .map(([request]) => request as Request)
      .filter((request) => request.url.includes("/publication/"));
    expect(publicationRequests.length).toBeGreaterThan(0);
    for (const request of publicationRequests) {
      expect(request.headers.get("Authorization")).toBe("Bearer token-after-refresh");
    }
  });

  it("returns to sign-in, saying so, when the server refuses a token", async () => {
    const session = { token: "token-the-server-no-longer-accepts" };
    vi.stubGlobal(
      "fetch",
      workbenchFetch((request) =>
        request.url.includes("/publication/") ? new Response(null, { status: 401 }) : undefined,
      ),
    );
    const user = userEvent.setup();

    render(<App authProvider={signedIn(session)} />);
    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "发布" }));

    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("登录已过期，请重新登录。");
  });

  it("returns to sign-in when there is no token left to sign a request with", async () => {
    // The session can be gone before a request is even attempted. That request
    // is refused without going out, which means it never produces a response —
    // so the refusal has to be announced by the code that short-circuits it.
    const session: { token: string | null } = { token: "token" };
    vi.stubGlobal("fetch", workbenchFetch());
    const user = userEvent.setup();

    render(<App authProvider={signedIn(session)} />);
    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();

    session.token = null;
    await user.click(screen.getByRole("link", { name: "发布" }));

    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("登录已过期，请重新登录。");
  });

  it("returns to sign-in when the session ends without a request being made", async () => {
    const session = { token: "token" };
    let announce: ((token: string | null) => void) | null = null;
    const authProvider: AuthProvider = {
      ...signedIn(session),
      onAuthStateChange: vi.fn().mockImplementation((listener) => {
        announce = listener;
        return () => undefined;
      }),
    };
    vi.stubGlobal("fetch", workbenchFetch());

    render(<App authProvider={authProvider} />);
    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();

    // Supabase, having failed to refresh: there is no session any more.
    act(() => announce?.(null));

    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("登录已过期，请重新登录。");
  });

  it("does not tell a writer who signed out that their login expired", async () => {
    const session: { token: string | null } = { token: "token" };
    let announce: ((token: string | null) => void) | null = null;
    const authProvider: AuthProvider = {
      ...signedIn(session),
      onAuthStateChange: vi.fn().mockImplementation((listener) => {
        announce = listener;
        return () => undefined;
      }),
    };
    vi.stubGlobal("fetch", workbenchFetch());
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.click(await screen.findByRole("button", { name: /账户与偏好/ }));
    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "退出登录" }),
    );
    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();

    // Supabase announces the sign-out the writer just performed themselves.
    session.token = null;
    act(() => announce?.(null));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));

    render(<App authProvider={authProvider} />);

    expect(await screen.findByRole("heading", { name: "立言阁" })).toBeInTheDocument();
    expect(screen.getByText("有感而发，知言而立")).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.queryByText("服务正常")).not.toBeInTheDocument();
  });

  it("only signs out once the writer confirms it", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) => {
      if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
      if (request.url.endsWith("/auth/me")) {
        return Response.json({ id: "user-1", email: "writer@example.com" });
      }
      if (request.url.includes("/tasks")) return Response.json({ items: [], next_cursor: null });
      return new Response(null, { status: 404 });
    }));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    // The actions fold into the address by default, so open them first.
    await user.click(await screen.findByRole("button", { name: /账户与偏好/ }));
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    // Undoing this costs a fresh email code, so the click alone must not do it.
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("退出登录？");
    expect(authProvider.signOut).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(authProvider.signOut).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "退出登录" }),
    );

    expect(await screen.findByLabelText("邮箱")).toBeInTheDocument();
    expect(authProvider.signOut).toHaveBeenCalledOnce();
  });

  it("lets a signed-out visitor pick the theme the workbench will open in", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue(null),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ status: "alive" })));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);
    await user.click(await screen.findByRole("button", { name: "主题: 浅色" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    // The same key AppShell reads, so the choice survives sign-in.
    expect(window.localStorage.getItem("liyan.theme")).toBe("dark");

    await user.click(screen.getByRole("button", { name: "主题: 深色" }));
    expect(document.documentElement.dataset.theme).toBe("system");
  });

  it("redirects a signed-in user to /task and keeps navigation in an app shell", async () => {
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
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
    expect(screen.getByRole("link", { name: "新建任务" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "发布" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/task");
  });

  it("stops marking 新建任务 as the current place once a task is open", async () => {
    /*
      React Router counts /task/:taskId as a descendant of /task, so the rail
      showed 新建任务 as selected while the writer was reading a task — two
      places selected at once, and the wrong one of them highlighted.

      Driven by the URL rather than by clicking the task in the rail: this suite
      shares one React Query client, so a task list cached by an earlier test
      decides what the rail lists, and the rule under test is about the route.
    */
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    const task = {
      id: "task-1",
      number: 1,
      display_name: "四天工作制的实际代价",
      first_source_title: "工时来源",
      additional_source_count: 0,
      current_version_id: "version-1",
      current_version_number: 1,
      created_at: "2026-09-02T10:00:00Z",
      last_activity_at: "2026-09-02T10:00:00Z",
      can_delete: true,
      delete_disabled_reason: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (request: Request) => {
        if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
        if (request.url.endsWith("/auth/me")) {
          return Response.json({ id: "user-1", email: "writer@example.com" });
        }
        if (request.url.includes("/tasks/task-1/versions")) {
          return Response.json({ items: [], historical_limit: 3 });
        }
        if (request.url.includes("/tasks/task-1/zhiyan")) {
          return Response.json({
            task_id: "task-1",
            task_version_id: "version-1",
            task_version_number: 1,
            sources: [],
            theme: null,
            liyan: { can_generate: false, unavailable_reason: null },
          });
        }
        if (request.url.includes("/tasks/task-1")) return Response.json(task);
        if (request.url.includes("/tasks")) {
          return Response.json({ items: [task], next_cursor: null });
        }
        return new Response(null, { status: 404 });
      }),
    );

    // At the creation page: this is where 新建任务 leads, so it is current.
    window.history.pushState({}, "", "/task");
    const atCreation = render(<App authProvider={authProvider} />);
    await waitFor(() => {
      expect(screen.getByRole("link", { name: "新建任务" }))
        .toHaveAttribute("aria-current", "page");
    });
    atCreation.unmount();

    // Reading a task is somewhere else, whatever the URL happens to start with.
    window.history.pushState({}, "", "/task/task-1");
    render(<App authProvider={authProvider} />);
    const newTask = await screen.findByRole("link", { name: "新建任务" });

    expect(newTask).not.toHaveAttribute("aria-current");
  });

  it("renders the signed-out, task, and publication routes in English", async () => {
    window.localStorage.setItem("liyan.locale", "en");
    const authProvider: AuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      sendEmailOtp: vi.fn(),
      verifyEmailOtp: vi.fn(),
      signOut: vi.fn().mockResolvedValue(undefined),
      onAuthStateChange: vi.fn().mockReturnValue(() => undefined),
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) => {
      if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
      if (request.url.endsWith("/auth/me")) {
        return Response.json({ id: "user-1", email: "writer@example.com" });
      }
      if (request.url.includes("/tasks")) return Response.json({ items: [], next_cursor: null });
      if (request.url.includes("/publication/")) return Response.json({ items: [], next_cursor: null });
      return new Response(null, { status: 404 });
    }));
    const user = userEvent.setup();

    render(<App authProvider={authProvider} />);

    expect(await screen.findByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "New task" })).toBeInTheDocument();
    expect(screen.getByText("Add 1–3 sources")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Publications" }));
    expect(await screen.findByRole("heading", { name: "Publish", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a draft" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");
  });
});

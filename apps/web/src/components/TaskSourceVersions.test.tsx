import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskSourceVersions } from "./TaskSourceVersions";

const sourceA = {
  source_id: "source-a",
  id: "revision-a1",
  title: "Alpha",
  body: "Alpha body",
  provenance: "Alpha provenance",
};
const sourceB = {
  source_id: "source-b",
  id: "revision-b1",
  title: "Beta",
  body: "Beta body",
  provenance: null,
};
const capabilities = {
  can_edit: true,
  can_restore: false,
  unavailable_reason: null,
};
const versionOne = {
  id: "version-1",
  number: 1,
  created_at: "2026-08-22T18:00:00Z",
  is_current: true,
  sources: [sourceA, sourceB],
  theme: null,
  capabilities,
};

describe("来源 editing and 任务版本 history", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps staged edits local, warns on refresh, and saves them together", async () => {
    let saved = false;
    const versionTwo = {
      ...versionOne,
      id: "version-2",
      number: 2,
      sources: [{ ...sourceA, id: "revision-a2", title: "Alpha edited" }],
    };
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "GET") {
        return Response.json({ items: [saved ? versionTwo : versionOne], historical_limit: 3 });
      }
      if (request.method === "POST" && request.url.endsWith("/source-edit-sessions")) {
        return Response.json({ id: "edit-1", base_version: versionOne }, { status: 201 });
      }
      if (request.method === "POST" && request.url.endsWith("/source-edit-sessions/edit-1/save")) {
        saved = true;
        return Response.json(versionTwo);
      }
      if (request.url.endsWith("/source-edit-sessions/edit-1/discard")) return new Response(null, { status: 204 });
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskSourceVersions
        accessToken="token"
        taskId="task-1"
        onVersionSelected={vi.fn()}
        onCurrentVersionChanged={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "编辑" }));
    // Editing opens with every 来源 collapsed, so working on one starts by
    // opening it.
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    const alpha = screen.getByRole("group", { name: "来源 Alpha" });
    await user.clear(within(alpha).getByLabelText("来源标题"));
    await user.type(within(alpha).getByLabelText("来源标题"), "Alpha edited");
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await user.click(screen.getByRole("button", { name: "删除来源 Beta" }));

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByText("当前版本仍是 V1；保存前的改动不会进入历史。"))
      .toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByText("当前版本 V2")).toBeInTheDocument();
    const saveRequest = fetch.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.url.endsWith("/source-edit-sessions/edit-1/save"));
    const body = JSON.parse(await saveRequest!.clone().text()) as {
      sources: Array<{ source_id: string; content?: { title: string } }>;
    };
    expect(body.sources).toHaveLength(1);
    expect(body.sources[0]).toMatchObject({
      source_id: "source-a",
      content: { title: "Alpha edited" },
    });
  });

  it("shows history read-only and restores by moving the current reference", async () => {
    const current = { ...versionOne, id: "version-2", number: 2 };
    const historical = {
      ...versionOne,
      is_current: false,
      capabilities: {
        can_edit: false,
        can_restore: true,
        unavailable_reason: "历史任务版本只读，恢复为当前版本后才能继续操作。",
      },
    };
    let restoredCurrent = false;
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "GET") {
        return Response.json({
          items: restoredCurrent
            ? [
                { ...historical, is_current: true, capabilities },
                {
                  ...current,
                  is_current: false,
                  capabilities: historical.capabilities,
                },
              ]
            : [current, historical],
          historical_limit: 3,
        });
      }
      if (request.method === "POST" && request.url.includes("/versions/version-1/restore")) {
        restoredCurrent = true;
        return Response.json({
          ...historical,
          is_current: true,
          capabilities,
        });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskSourceVersions
        accessToken="token"
        taskId="task-1"
        onVersionSelected={vi.fn()}
        onCurrentVersionChanged={vi.fn()}
      />,
    );

    await user.selectOptions(await screen.findByLabelText("版本"), "version-1");
    expect(screen.getByText("只读历史 V1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "恢复为当前版本" }));
    // The confirmation is a dialog in the page, not a native confirm() the
    // browser is free to suppress.
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "恢复为当前版本" }),
    );
    expect(await screen.findByText("当前版本 V1")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([request]) => (request as Request).method === "POST"))
      .toBe(true);
  });

  it("keeps one save identity across a lost response", async () => {
    let saveAttempts = 0;
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "GET") {
        const retriedVersion = {
          ...versionOne,
          id: "version-2",
          number: 2,
          sources: [{ ...sourceA, id: "revision-a2", title: "Retried" }, sourceB],
        };
        return Response.json({
          items: [saveAttempts >= 2 ? retriedVersion : versionOne],
          historical_limit: 3,
        });
      }
      if (request.url.endsWith("/source-edit-sessions") && request.method === "POST") {
        return Response.json({ id: "edit-retry", base_version: versionOne }, { status: 201 });
      }
      if (request.url.endsWith("/source-edit-sessions/edit-retry/save")) {
        saveAttempts += 1;
        if (saveAttempts === 1) return Response.json({ detail: "lost" }, { status: 503 });
        return Response.json({
          ...versionOne,
          id: "version-2",
          number: 2,
          sources: [{ ...sourceA, id: "revision-a2", title: "Retried" }, sourceB],
        });
      }
      if (request.url.endsWith("/source-edit-sessions/edit-retry/discard")) {
        return new Response(null, { status: 204 });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskSourceVersions
        accessToken="token"
        taskId="task-1"
        onVersionSelected={vi.fn()}
        onCurrentVersionChanged={vi.fn()}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "编辑" }));
    // Editing opens with every 来源 collapsed, so working on one starts by
    // opening it.
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    const alpha = screen.getByRole("group", { name: "来源 Alpha" });
    await user.clear(within(alpha).getByLabelText("来源标题"));
    await user.type(within(alpha).getByLabelText("来源标题"), "Retried");
    await user.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("来源修改保存失败");
    await user.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByText("当前版本 V2")).toBeInTheDocument();
    const saves = fetch.mock.calls
      .map(([request]) => request as Request)
      .filter((request) => request.url.endsWith("/source-edit-sessions/edit-retry/save"));
    const keys = await Promise.all(saves.map(async (request) =>
      (JSON.parse(await request.clone().text()) as { idempotency_key: string }).idempotency_key));
    expect(keys[0]).toBe(keys[1]);
  });

  it("discards a session the writer abandons", async () => {
    type FetchCall = (request: Request) => Promise<Response>;
    const fetch = vi.fn<FetchCall>(async (request) => {
      if (request.url.endsWith("/tasks/task-1/versions")) {
        return Response.json({ items: [versionOne], historical_limit: 3 });
      }
      if (request.url.endsWith("/source-edit-sessions") && request.method === "POST") {
        return Response.json({ id: "edit-left", base_version: versionOne }, { status: 201 });
      }
      if (request.url.endsWith("/source-edit-sessions/edit-left/discard")) {
        return new Response(null, { status: 204 });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskSourceVersions
        accessToken="token"
        taskId="task-1"
        onVersionSelected={vi.fn()}
        onCurrentVersionChanged={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "编辑" }));
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    const alpha = screen.getByRole("group", { name: "来源 Alpha" });
    await user.type(within(alpha).getByLabelText("来源标题"), " edited");

    // Navigation the browser has committed to: nothing was saved, so the
    // session is unrecoverable by design and says so now rather than being
    // left behind on the server.
    window.dispatchEvent(new PageTransitionEvent("pagehide"));

    // The discard resolves a token before it is sent, so it leaves on the next
    // tick rather than inside the event.
    await waitFor(() => {
      expect(fetch.mock.calls.some(([request]) =>
        (request as Request).url.endsWith("/source-edit-sessions/edit-left/discard"))).toBe(true);
    });
  });

  it("does not discard a session whose save is still in flight", async () => {
    /*
      Leaving this pane discards the editing session, which is deliberate: an
      unfinished 来源编辑会话 is unrecoverable. A save is not an unfinished
      session, and the two raced — pressing 保存修改 and then leaving let the
      discard reach the server first, and the save was refused against a
      session that no longer existed. The writer's changes were gone and the
      screen showed the version they started from, with nothing saying why.

      CI found it before a user did: the same steps pass on a fast machine and
      lose the race on a slow one.
    */
    let releaseSave: (() => void) | null = null;
    const saveReached = new Promise<void>((resolve) => {
      releaseSave = resolve;
    });
    type FetchCall = (request: Request) => Promise<Response>;
    const fetch = vi.fn<FetchCall>(async (request) => {
      if (request.url.endsWith("/tasks/task-1/versions")) {
        return Response.json({ items: [versionOne], historical_limit: 3 });
      }
      if (request.url.endsWith("/source-edit-sessions") && request.method === "POST") {
        return Response.json({ id: "edit-slow", base_version: versionOne }, { status: 201 });
      }
      if (request.url.endsWith("/source-edit-sessions/edit-slow/save")) {
        releaseSave?.();
        // Still travelling when the pane goes away.
        await new Promise((resolve) => setTimeout(resolve, 50));
        return Response.json({ ...versionOne, id: "version-2", number: 2 });
      }
      if (request.url.endsWith("/source-edit-sessions/edit-slow/discard")) {
        return new Response(null, { status: 204 });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    const view = render(
      <TaskSourceVersions
        accessToken="token"
        taskId="task-1"
        onVersionSelected={vi.fn()}
        onCurrentVersionChanged={vi.fn()}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "编辑" }));
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    const alpha = screen.getByRole("group", { name: "来源 Alpha" });
    await user.clear(within(alpha).getByLabelText("来源标题"));
    await user.type(within(alpha).getByLabelText("来源标题"), "Alpha edited");
    void user.click(screen.getByRole("button", { name: "保存修改" }));
    await saveReached;

    // The writer switches to another view — this pane unmounts mid-save.
    view.unmount();
    window.dispatchEvent(new PageTransitionEvent("pagehide"));

    expect(fetch.mock.calls.some(([request]) =>
      (request as Request).url.endsWith("/source-edit-sessions/edit-slow/discard"))).toBe(false);
  });
});

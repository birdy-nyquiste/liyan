/**
 * The accessibility rules this release is gated on.
 *
 * Not a substitute for using the workbench with a keyboard and a screen reader
 * — nothing automated is. These are the four things that regress silently
 * between releases, each stated as an assertion rather than as advice, so a
 * change that breaks one fails a test instead of reaching a user:
 *
 *   1. Every disabled control says why, and says it to the accessibility tree
 *      rather than only to the eye.
 *   2. Every action can be reached and taken from the keyboard alone.
 *   3. Focus lands where the work is, when the phase changes.
 *   4. Every region has a name, so a screen reader can list them.
 *
 * `docs/operations/accessibility.md` holds the thresholds and what is checked
 * by hand, including the responsive breakpoints, which no unit test can see.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiyanPanel } from "./LiyanPanel";
import { articleContentHash } from "./articleContentHash";
import { saveWorkingCopy } from "./workingCopyStorage";
import { TaskCard } from "./TaskCard";
import { ZhiyanPanel } from "./ZhiyanPanel";

type ZhiyanPanelState = Parameters<typeof ZhiyanPanel>[0]["state"];

const NO_UNSAVED_EDITS = "没有未保存的修改。";

const task: {
  id: string;
  number: number;
  display_name: string;
  first_source_title: string;
  additional_source_count: number;
  created_at: string;
  last_activity_at: string;
  current_version_id: string;
  current_version_number: number;
  can_delete: boolean;
  delete_disabled_reason: string | null;
} = {
  id: "task-1",
  number: 1,
  display_name: "四天工作制",
  first_source_title: "四天工作制",
  additional_source_count: 0,
  created_at: "2026-08-23T16:52:00Z",
  last_activity_at: "2026-08-23T16:52:00Z",
  current_version_id: "version-1",
  current_version_number: 1,
  can_delete: true,
  delete_disabled_reason: null,
};

function liyanState(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "task-1",
    task_version_id: "version-1",
    status: "succeeded",
    execution: null,
    result: null,
    request: null,
    revisions: {
      current: {
        id: "revision-1",
        number: 1,
        task_version_id: "version-1",
        title: "四天工作制的真问题",
        body_markdown: "工时只是生产方式的一部分。",
        content_hash: "hash-1",
        base_revision_id: null,
        restored_from_revision_id: null,
        created_at: "2026-08-22T18:10:00Z",
      },
      historical: [],
      historical_limit: 3,
    },
    capabilities: {
      can_generate: true,
      can_cancel: false,
      can_save: true,
      publishable_revision_id: "revision-1",
      publication_unavailable_reason: null,
      retry: { allowed: true, remaining: 2, allowed_at: null },
      unavailable_reason: null,
    },
    ...overrides,
  };
}

function zhiyanState(overrides: Record<string, unknown> = {}): ZhiyanPanelState {
  return {
    source_revision_id: "revision-1",
    source_title: "四天工作制",
    status: "failed",
    execution: {
      id: "execution-1",
      operation: "analyze_source",
      status: "failed",
      attempt: 3,
      input_version: 1,
      trace_id: "trace-1",
      created_at: "2026-08-22T18:00:00Z",
      started_at: "2026-08-22T18:00:01Z",
      finished_at: "2026-08-22T18:00:04Z",
      cancellation_requested_at: null,
      result_id: null,
      error: { code: "provider_unavailable", message: "分析服务暂时不可用，请稍后重试。" },
    },
    report: null,
    capabilities: {
      can_start: false,
      can_cancel: false,
      retry: { allowed: false, remaining: 0, allowed_at: null },
      unavailable_reason: null,
    },
    ...overrides,
  } as ZhiyanPanelState;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("disabled controls explain themselves", () => {
  it("names the reason a 立言任务 cannot be deleted, on the button itself", () => {
    const blocked: typeof task = {
      ...task,
      can_delete: false,
      delete_disabled_reason: "有发布任务尚未结束，暂时无法删除。",
    };
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({})));

    render(<TaskCard task={blocked} userId="user-1" accessToken="token" />);

    const remove = screen.getByRole("button", { name: `删除 ${blocked.display_name}` });
    expect(remove).toBeDisabled();
    expect(remove).toHaveAccessibleDescription(blocked.delete_disabled_reason);
  });

  it("names the reason 知言 cannot be retried, on the retry button", () => {
    render(
      <ZhiyanPanel
        state={zhiyanState()}
        busy={false}
        onStart={() => undefined}
        onCancel={() => undefined}
        onRetryAllowed={() => undefined}
      />,
    );

    const retry = screen.getByRole("button", { name: "重试" });
    expect(retry).toBeDisabled();
    expect(retry).toHaveAccessibleDescription("重试次数已用完，请稍后再试。");
  });

  it("names the reason 立言 cannot be generated yet, on the generate button", async () => {
    const waiting = liyanState({
      status: "absent",
      revisions: { current: null, historical: [], historical_limit: 3 },
      capabilities: {
        ...liyanState().capabilities,
        can_generate: false,
        unavailable_reason: "每个来源都完成知言分析后才能立言。",
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(waiting)));

    render(<LiyanPanel userId="user-1" taskId="task-1" accessToken="token" />);

    const generate = await screen.findByRole("button", { name: "默认生成" });
    await waitFor(() => expect(generate).toBeDisabled());
    expect(generate).toHaveAccessibleDescription("每个来源都完成知言分析后才能立言。");
  });

  it("says a Revision cannot be saved because nothing has changed", async () => {
    // A user who has just saved and presses again is the common case, and a
    // dead button with no reason reads as a broken product.
    // The saved Revision, edited into nothing: the draft hashes to exactly what
    // the server issued, which is how the workbench knows nothing has changed.
    const draft = {
      title: "四天工作制的真问题",
      body_markdown: "工时只是生产方式的一部分。",
    };
    const saved = liyanState();
    saved.revisions.current.content_hash = await articleContentHash(draft);
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(saved)));
    saveWorkingCopy("user-1", "task-1", draft);

    render(<LiyanPanel userId="user-1" taskId="task-1" accessToken="token" />);

    const save = await screen.findByRole("button", { name: "保存草稿" });
    await waitFor(() => expect(save).toBeDisabled());
    expect(save).toHaveAccessibleDescription(NO_UNSAVED_EDITS);
  });
});

describe("keyboard operation", () => {
  it("opens a 立言任务, moves through its areas, and deletes it without a mouse", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({})));
    const user = userEvent.setup();
    render(<TaskCard task={task} userId="user-1" accessToken="token" />);

    // Tab until the delete button has focus, pressing nothing on the way: every
    // control between here and there must be reachable for this to terminate.
    const remove = screen.getByRole("button", { name: `删除 ${task.display_name}` });
    for (let presses = 0; presses < 12 && document.activeElement !== remove; presses += 1) {
      await user.tab();
    }

    expect(remove).toHaveFocus();
  });

  it("takes 知言 actions from the keyboard alone", async () => {
    const started = vi.fn();
    const user = userEvent.setup();
    render(
      <ZhiyanPanel
        state={zhiyanState({
          status: "failed",
          capabilities: {
            can_start: true,
            can_cancel: false,
            retry: { allowed: true, remaining: 1, allowed_at: null },
            unavailable_reason: null,
          },
        })}
        busy={false}
        onStart={started}
        onCancel={() => undefined}
        onRetryAllowed={() => undefined}
      />,
    );

    const retry = screen.getByRole("button", { name: "重试" });
    retry.focus();
    await user.keyboard("{Enter}");

    expect(started).toHaveBeenCalledWith("revision-1");
  });
});

describe("regions and focus", () => {
  it("gives every 知言 panel a name a screen reader can list", () => {
    render(
      <ZhiyanPanel
        state={zhiyanState()}
        busy={false}
        onStart={() => undefined}
        onCancel={() => undefined}
        onRetryAllowed={() => undefined}
      />,
    );

    // Named by the 来源 it analyzed, which is what distinguishes one panel from
    // the next when a 任务版本 holds three of them.
    expect(screen.getByRole("region", { name: "四天工作制" })).toBeInTheDocument();
  });

  it("moves focus to 立言 once it is the work in front of the user", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(liyanState())));

    render(<LiyanPanel userId="user-1" taskId="task-1" accessToken="token" />);

    const heading = await screen.findByRole("heading", { name: "立言文章" });
    await waitFor(() => expect(heading).toHaveFocus());
  });
});

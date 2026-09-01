import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AccessToken,
  confirmTaskCreationSession,
  createUrlSource,
  deleteTaskCreationSource,
  getTaskCreationSession,
  refusalWithoutTiming,
  type SessionSourceResponse,
  type TaskCreationSessionResponse,
  type TaskSummaryResponse,
} from "@workbench/api/client";
import { SOURCE_PREPARATION_POLL_MS } from "@workbench/components/pollIntervals";

import { describeAge, expiryWarning } from "./age";
import {
  type AddedTimes,
  closeBasket,
  readAddedTimes,
  readConfirmationKey,
  recordAdded,
} from "./basketId";

import {
  type CurrentPage,
  describePage,
  normalizeUrl,
  readCurrentPage,
  shortenUrl,
} from "./currentPage";

type BasketProps = {
  accessToken: AccessToken;
  basketId: string;
  /**
   * Whether this basket was found in storage rather than opened just now.
   *
   * It changes two things: the panel says so, and an empty one is treated as
   * collected rather than as new. A basket the user opened a second ago is
   * also empty, and telling them it expired would be nonsense.
   */
  recovered: boolean;
  onCreated(task: TaskSummaryResponse): void;
  /** A recovered basket the server no longer has anything for. */
  onCollected(): void;
};

/**
 * The warnings this confirmation accepts, keyed by 来源 and its input version.
 *
 * There is no separate "are you sure": the warning is on the row directly
 * above the button, and pressing it is the acceptance. The guard being
 * satisfied is that the user saw it — not that they clicked twice.
 *
 * The version matters. Accepting a warning accepts *that* reading of the 来源;
 * if the 来源 changed after the panel drew it, the server refuses rather than
 * taking an agreement about something else.
 */
function acceptedWarnings(sources: SessionSourceResponse[]): Record<string, number> {
  const accepted: Record<string, number> = {};
  for (const source of sources) {
    if (source.warnings.length > 0) accepted[source.id] = source.input_version;
  }
  return accepted;
}

/** Whether anything in the basket is still being fetched. */
function isWorking(session: TaskCreationSessionResponse | null): boolean {
  return session?.sources.some((source) => source.status === "processing") ?? false;
}

/**
 * Why 确认创建任务 cannot be pressed, in a sentence a user can act on.
 *
 * The server sends a reason too, but it says "wait for every source to be
 * ready" for a failed 来源 as well as a fetching one — and a failure will never
 * become ready. Waiting is not what that user should do; removing it is.
 */
function confirmationBlocker(session: TaskCreationSessionResponse | null): string | null {
  if (!session || session.source_count === 0) return null;
  if (session.sources.some((source) => source.status === "failure")) {
    return "移除抓取失败的来源，才能创建任务。";
  }
  if (isWorking(session)) return "等待抓取完成后即可创建任务。";
  return null;
}

/** Why 添加当前页面 cannot be pressed, checked before the click rather than after. */
function additionBlocker(
  session: TaskCreationSessionResponse | null,
  page: CurrentPage | null,
): string | null {
  if (session && !session.can_add) return "已达三条上限，移除一条才能再添加。";
  if (page?.refusal) return page.refusal;
  // The server refuses a repeated URL within one session. The panel holds the
  // session, so it can say so without spending a request to be told.
  //
  // It compares normalized forms because `provenance` is what the server wrote,
  // not what the tab said. A 来源 still being fetched has no provenance yet, so
  // a very fast second click can slip past this — the server refuses that one,
  // and its refusal is shown.
  if (session && page && session.sources.some((source) => normalizedSourceUrl(source) === page.normalizedUrl)) {
    return "这一页已经在来源里了。";
  }
  return null;
}

/** The address a 来源 came from, which the server keeps as its provenance. */
function sourceUrl(source: SessionSourceResponse): string | null {
  return source.provenance;
}

function normalizedSourceUrl(source: SessionSourceResponse): string | null {
  return source.provenance ? normalizeUrl(source.provenance) : null;
}

export function Basket({
  accessToken,
  basketId,
  recovered,
  onCreated,
  onCollected,
}: BasketProps) {
  const [session, setSession] = useState<TaskCreationSessionResponse | null>(null);
  const [page, setPage] = useState<CurrentPage | null>(null);
  const [addedTimes, setAddedTimes] = useState<AddedTimes>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Set while this panel is open, so a poll that returns late cannot write. */
  const open = useRef(true);

  useEffect(() => {
    open.current = true;
    return () => {
      open.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const next = await getTaskCreationSession(accessToken, basketId);
    if (open.current) setSession(next);
    return next;
  }, [accessToken, basketId]);

  useEffect(() => {
    void readAddedTimes().then((times) => {
      if (open.current) setAddedTimes(times);
    });
    void readCurrentPage()
      .catch(() => describePage(undefined, undefined))
      .then((current) => {
        if (open.current) setPage(current);
      });
    void refresh()
      .then(async (first) => {
        // A recovered basket the server has nothing for was collected while
        // the panel was closed. Saying so would be telling the user about
        // something they cannot act on; letting go of the id quietly and
        // returning to 主屏 leaves them somewhere that works.
        if (recovered && first.source_count === 0) {
          await closeBasket();
          if (open.current) onCollected();
        }
      })
      .catch(() => {
        if (open.current) setError("暂时无法读取来源，请重试。");
      });
  }, [refresh, recovered, onCollected]);

  /**
   * Ask again while anything is still being fetched, and stop when nothing is.
   *
   * Fetching happens on the server whether the panel is open or not, so this
   * poll is only about what is on screen. It ends the moment the basket
   * settles, rather than running for as long as the panel does.
   */
  useEffect(() => {
    if (!isWorking(session)) return;
    const timer = setInterval(() => {
      void refresh().catch(() => undefined);
    }, SOURCE_PREPARATION_POLL_MS);
    return () => clearInterval(timer);
  }, [session, refresh]);

  async function addCurrentPage() {
    if (!page || page.refusal) return;
    setBusy(true);
    setError(null);
    try {
      const added = await createUrlSource(accessToken, basketId, crypto.randomUUID(), page.url);
      await recordAdded(added.id);
      setAddedTimes(await readAddedTimes());
      await refresh();
    } catch (thrown) {
      // 402 and the per-user ceiling are written for a user and are the only
      // thing that explains the button doing nothing. Anything else is ours.
      setError(refusalWithoutTiming(thrown) ?? "添加失败，请稍后重试。");
    } finally {
      if (open.current) setBusy(false);
    }
  }

  async function confirm() {
    const current = session;
    if (!current?.can_confirm) return;
    setBusy(true);
    setError(null);
    try {
      const task = await confirmTaskCreationSession(
        accessToken,
        await readConfirmationKey(),
        basketId,
        current.sources.map((one) => one.id),
        acceptedWarnings(current.sources),
      );
      // The basket is let go only once the task exists. Dropping it first
      // would, on a failed confirmation, lose the way back to 来源 that are
      // still on the server and have already been paid for.
      await closeBasket();
      onCreated(task);
    } catch (thrown) {
      setError(refusalWithoutTiming(thrown) ?? "创建任务失败，请重试。");
    } finally {
      if (open.current) setBusy(false);
    }
  }

  async function remove(sourceId: string) {
    setBusy(true);
    setError(null);
    try {
      await deleteTaskCreationSource(accessToken, sourceId);
      await refresh();
    } catch {
      setError("移除失败，请重试。");
    } finally {
      if (open.current) setBusy(false);
    }
  }

  const sources = session?.sources ?? [];
  const cannotAdd = additionBlocker(session, page);
  const blocker = confirmationBlocker(session);
  const canConfirm = Boolean(session?.can_confirm) && !busy;
  const expiring = sources.length > 0 ? expiryWarning(addedTimes) : null;

  return (
    <>
      <div className="panel__body">
        {recovered && sources.length > 0 ? (
          <p className="form-hint">上次还有一个没建完的任务。</p>
        ) : null}
        {sources.length === 0 ? (
          <p className="basket__empty">
            还没有来源。
            <br />
            翻到想收集的页面，点下面的「添加当前页面」。
          </p>
        ) : (
          <ul className="basket">
            {sources.map((source) => (
              <SourceRow
                key={source.id}
                source={source}
                age={describeAge(addedTimes[source.id])}
                busy={busy}
                onRemove={remove}
              />
            ))}
          </ul>
        )}
        {expiring ? <p className="basket__expiry">{expiring}</p> : null}
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <div className="panel__foot">
        <p className="panel__foot-note">
          {cannotAdd ?? `当前页面 · ${page ? shortenUrl(page.url) : "读取中…"}`}
        </p>
        <button
          className="button button--quiet"
          type="button"
          disabled={busy || Boolean(cannotAdd)}
          onClick={() => void addCurrentPage()}
        >
          添加当前页面
        </button>
        {blocker ? <p className="panel__foot-note">{blocker}</p> : null}
        <button
          className="button"
          type="button"
          disabled={!canConfirm}
          aria-busy={busy}
          onClick={() => void confirm()}
        >
          {session && session.source_count > 0
            ? `确认创建任务（${session.source_count} 条来源）`
            : "确认创建任务"}
        </button>
      </div>
    </>
  );
}

function SourceRow({
  source,
  age,
  busy,
  onRemove,
}: {
  source: SessionSourceResponse;
  age: string | null;
  busy: boolean;
  onRemove(sourceId: string): Promise<void>;
}) {
  const address = sourceUrl(source);
  const name = source.title?.trim() || (address ? shortenUrl(address) : "正在抓取…");
  return (
    <li className="basket__item">
      <p className={`basket__title${source.title ? "" : " basket__title--pending"}`}>{name}</p>
      <div className="basket__meta">
        <StatusPill source={source} />
        {/* One or the other: the address is what a user recognizes, and it
            gives way only once the age is the more useful of the two. */}
        <span className="basket__host">{age ?? (address ? shortenUrl(address) : "")}</span>
        <button
          className="basket__remove"
          type="button"
          disabled={busy}
          aria-label={`移除 ${name}`}
          onClick={() => void onRemove(source.id)}
        >
          ×
        </button>
      </div>
      {source.failure ? <p className="basket__why">{source.failure.message}</p> : null}
    </li>
  );
}

function StatusPill({ source }: { source: SessionSourceResponse }) {
  if (source.status === "processing") {
    return <span className="basket__pill basket__pill--busy">处理中</span>;
  }
  if (source.status === "failure") {
    // A capture that produced nothing settles to zero, so this one cost the
    // user nothing. Saying so belongs next to the failure, where they are
    // deciding whether it was worth trying.
    return <span className="basket__pill basket__pill--danger">抓取失败 · 未消耗额度</span>;
  }
  const length = source.body?.length ?? 0;
  if (source.status === "warning") {
    const warning = source.warnings[0]?.message ?? "内容可能不足以支撑知言分析。";
    return (
      <span className="basket__pill basket__pill--warn" title={warning}>
        正文偏薄 · {length} 字
      </span>
    );
  }
  return <span className="basket__pill basket__pill--ok">{length} 字</span>;
}

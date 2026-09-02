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
import { MAX_THEME_CHARACTERS } from "@workbench/components/themeLimits";
import { useInterfaceLocale } from "@workbench/interfaceLocale";

import { describeAge, expiryWarning } from "./age";
import {
  type AddedSources,
  closeBasket,
  readAddedSources,
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
  added: AddedSources,
): string | null {
  if (session && !session.can_add) return "已达三条上限，移除一条才能再添加。";
  if (page?.refusal) return page.refusal;
  // The server refuses a repeated URL within one session. The panel holds the
  // session, so it can say so without spending a request to be told.
  //
  // It compares normalized forms because `provenance` is what the server wrote
  // and not what the tab said. A 来源 still being fetched has no provenance at
  // all, which is why what the panel submitted is compared too — otherwise this
  // page could be added a second time for as long as the first fetch runs.
  if (session && page) {
    const already = session.sources.some(
      (source) =>
        normalizedSourceUrl(source) === page.normalizedUrl
        || (added[source.id] && normalizeUrl(added[source.id].url) === page.normalizedUrl),
    );
    if (already) return "该页面已添加。";
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
  const [added, setAdded] = useState<AddedSources>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The 主题, typed here or left empty. Only in memory: a basket outlives the
  // popup, and a half-typed 主题 restored days later beside 来源 the user has
  // forgotten would be worse than an empty box.
  const [theme, setTheme] = useState("");
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
    void readAddedSources().then((known) => {
      if (open.current) setAdded(known);
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
      const created = await createUrlSource(accessToken, basketId, crypto.randomUUID(), page.url);
      await recordAdded(created.id, page.url);
      setAdded(await readAddedSources());
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
    if (!current?.can_confirm || theme.length > MAX_THEME_CHARACTERS) return;
    setBusy(true);
    setError(null);
    try {
      const task = await confirmTaskCreationSession(
        accessToken,
        await readConfirmationKey(),
        basketId,
        current.sources.map((one) => one.id),
        acceptedWarnings(current.sources),
        theme.trim() || null,
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
  const cannotAdd = additionBlocker(session, page, added);
  const themeTooLong = theme.length > MAX_THEME_CHARACTERS;
  const blocker = confirmationBlocker(session);
  const canConfirm = Boolean(session?.can_confirm) && !busy && !themeTooLong;
  const expiring = sources.length > 0 ? expiryWarning(added) : null;

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
                age={describeAge(added[source.id]?.at)}
                submittedUrl={added[source.id]?.url ?? null}
                busy={busy}
                onRemove={remove}
              />
            ))}
          </ul>
        )}
        {sources.length > 0 ? (
          <label className="basket__theme" htmlFor="basket-theme">
            主题（可留空）
            <input
              id="basket-theme"
              value={theme}
              maxLength={MAX_THEME_CHARACTERS}
              placeholder="这批来源共同在谈什么"
              onChange={(event) => setTheme(event.target.value)}
            />
            <span className="form-hint">
              一句话，最多 {MAX_THEME_CHARACTERS} 字。留空即不生成主题知言报告；
              想让 Agent 提炼候选，请到工作台创建。
            </span>
          </label>
        ) : null}
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
  submittedUrl,
  busy,
  onRemove,
}: {
  source: SessionSourceResponse;
  age: string | null;
  /** The address the panel submitted, which it remembers whatever happens. */
  submittedUrl: string | null;
  busy: boolean;
  onRemove(sourceId: string): Promise<void>;
}) {
  const { domainMessage } = useInterfaceLocale();
  // `provenance` only exists once a fetch has succeeded, so a failed 来源 has
  // none — and a row that cannot say which page failed is no use at all to the
  // person deciding what to do about it. What the panel submitted stands in.
  const address = sourceUrl(source) ?? submittedUrl;
  const title = source.title?.trim();
  const name = title || (address ? shortenUrl(address) : "正在抓取…");
  return (
    <li className="basket__item">
      <p className={`basket__title${title ? "" : " basket__title--pending"}`}>{name}</p>
      <div className="basket__meta">
        <StatusPill source={source} />
        {/* One line, and never the same thing twice: a 来源 with no title is
            already named by its address, so repeating it here would spend the
            row's only other line saying nothing. */}
        <span className="basket__host">{age ?? (title && address ? shortenUrl(address) : "")}</span>
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
      {/* The server's failure message is written for whoever reads the logs.
          工作台 already owns a sentence per code for the person looking at it,
          and both clients saying the same thing about the same code is the
          whole reason that table exists. */}
      {source.failure ? (
        <p className="basket__why">
          {domainMessage(source.failure.message, source.failure.code)}
        </p>
      ) : null}
    </li>
  );
}

/**
 * The short label for a warning, by what the warning actually is.
 *
 * Not one wording for all of them. A 23,302-character article came back
 * `warning` because it had no `<title>`, and a pill that said 正文偏薄 was
 * telling the user something plainly untrue about their 来源.
 */
const WARNING_LABEL: Record<string, string> = {
  short_body: "正文偏薄",
  missing_title: "缺少标题",
  missing_provenance: "缺少出处",
};

function StatusPill({ source }: { source: SessionSourceResponse }) {
  const { domainMessage } = useInterfaceLocale();
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
  if (source.status === "warning" && source.warnings.length > 0) {
    const [first] = source.warnings;
    // The full sentence is 工作台's, so both clients say the same thing about
    // the same code; the pill carries the short form and the title the whole.
    return (
      <span
        className="basket__pill basket__pill--warn"
        title={domainMessage(first.message, first.code)}
      >
        {WARNING_LABEL[first.code] ?? "需确认"} · {length} 字
      </span>
    );
  }
  return <span className="basket__pill basket__pill--ok">{length} 字</span>;
}

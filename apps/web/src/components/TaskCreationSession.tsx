import { type FormEvent, useCallback, useEffect, useLayoutEffect, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, FileText, Lock, Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useInterfaceLocale } from "../interfaceLocale";
import { RunningNotice } from "./RunningNotice";

import {
  cancelExecution,
  confirmTaskCreationSession,
  createFileSource,
  createPastedSource,
  createUrlSource,
  deleteTaskCreationSource,
  editFileSourceContent,
  editPastedSource,
  editUrlSourceContent,
  getTaskCreationSession,
  refusalWithoutTiming,
  retryFileSource,
  retryUrlSource,
  type SessionSourceResponse,
  type SourceInput,
  type TaskCreationSessionResponse,
  type AccessToken,
} from "../api/client";
import { BuyCreditsLink } from "./BuyCreditsLink";
import { ThemeChoice } from "./ThemeChoice";
import { MAX_THEME_CHARACTERS } from "./themeLimits";
import { isCreditRefusal } from "./creditRefusal";
import type { TaskSummary } from "../auth/state";
import { SOURCE_PREPARATION_POLL_MS } from "./pollIntervals";
import { getAccount } from "../api/client";

type DraftSource = { title: string; body: string; provenance: string };
const CREATION_SESSION_KEY = "liyan.creationSession";
const emptyDraft: DraftSource = { title: "", body: "", provenance: "" };
const sourceKindLabels = { pasted: "粘贴文本", url: "公共文章链接", file: "上传文件" };
// A fetched or parsed body is not something the writer wrote, and saying so is
// the difference between "check your text" and "check what we read".
const bodyLabels = { pasted: "来源正文", url: "抓取正文", file: "解析正文" };
const sourceStatusLabels = {
  processing: "处理中",
  ready: "已就绪",
  warning: "有警告",
  failure: "处理失败",
};

function SourceCard({
  accessToken,
  source,
  index,
  busy,
  onEditingChange,
  onChanged,
  onBusy,
  onError,
  expanded,
  onToggle,
}: {
  accessToken: AccessToken;
  source: SessionSourceResponse;
  index: number;
  busy: boolean;
  onEditingChange(sourceId: string, dirty: boolean): void;
  onChanged(): Promise<void>;
  onBusy(busy: boolean): void;
  onError(message: string | null): void;
  expanded: boolean;
  onToggle(): void;
}) {
  const { t, domainMessage } = useInterfaceLocale();
  const [draft, setDraft] = useState<DraftSource>({
    title: source.title ?? "",
    body: source.body ?? "",
    provenance: source.provenance ?? "",
  });
  const editing = draft.title !== (source.title ?? "")
    || draft.body !== (source.body ?? "")
    || draft.provenance !== (source.provenance ?? "");

  useEffect(() => {
    setDraft({
      title: source.title ?? "",
      body: source.body ?? "",
      provenance: source.provenance ?? "",
    });
  }, [source.body, source.provenance, source.title]);

  useEffect(() => {
    onEditingChange(source.id, editing);
    return () => onEditingChange(source.id, false);
  }, [editing, onEditingChange, source.id]);

  async function perform(action: () => Promise<unknown>, message: string) {
    onBusy(true);
    onError(null);
    try {
      await action();
      await onChanged();
    } catch {
      onError(message);
    } finally {
      onBusy(false);
    }
  }

  async function save() {
    const input: SourceInput = { ...draft, provenance: draft.provenance || null };
    await perform(
      () => source.kind === "pasted"
        ? editPastedSource(accessToken, source.id, input)
        : source.kind === "url"
          ? editUrlSourceContent(accessToken, source.id, input)
          : editFileSourceContent(accessToken, source.id, input),
      t("保存来源失败，请重试。"),
    );
  }

  return (
    <article className={`source-operation source-operation--${source.status}`}>
      <button
        className="source-operation__summary"
        type="button"
        aria-expanded={expanded}
        aria-label={`${t("编辑来源")} ${source.title || t("未命名来源")}`}
        onClick={onToggle}
      >
      <span className="source-operation__status">
        <strong>
          <span className="source-operation__index">{index}</span>
          {expanded ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
          {t(sourceKindLabels[source.kind])} · {source.title || t("未命名来源")}
        </strong>
        <span className={`source-chip source-chip--${source.status}`}>{t(sourceStatusLabels[source.status])}</span>
      </span>
      </button>

      {/*
        * Each kind is defined by something different: pasted text by what was
        * typed, a link by where it points, a file by which file it was. The one
        * that defines this source is shown on it.
        */}
      {source.kind === "url" && source.provenance ? (
        <a className="source-meta" href={source.provenance} target="_blank" rel="noreferrer noopener">
          <ExternalLink size={14} aria-hidden="true" />
          <span className="source-meta__value">{source.provenance}</span>
        </a>
      ) : null}
      {source.kind === "file" && source.provenance ? (
        <p className="source-meta">
          <FileText size={14} aria-hidden="true" />
          <span className="source-meta__value">{source.provenance}</span>
        </p>
      ) : null}
      {/* What is wrong with a source belongs on the source, where it is read
          without opening anything. */}
      {source.failure ? (
        <p role="alert" className="source-note source-note--failure">
          {domainMessage(source.failure.message, source.failure.code)}
        </p>
      ) : null}
      {source.status === "processing" ? (
        <RunningNotice label={t("正在处理来源…")} />
      ) : null}
      {source.warnings.map((warning) => (
        <p className="source-note source-note--warning" key={warning.code}>
          {domainMessage(warning.message, warning.code)}
        </p>
      ))}
      {expanded ? <div className="source-operation__editor">
      {source.capabilities.can_edit ? (
        // Leaving a field is what commits it; a button that only repeated that
        // was one more thing standing between a source and the task.
        <div className="creation-form" onBlur={() => { if (editing) void save(); }}>
          <label htmlFor={`source-title-${source.id}`}>{t("来源标题")}</label>
          <input id={`source-title-${source.id}`} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
          <label htmlFor={`source-body-${source.id}`}>{t(bodyLabels[source.kind])}</label>
          <textarea id={`source-body-${source.id}`} rows={8} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} />
          {source.kind === "pasted" ? (
            <>
              <label htmlFor={`source-provenance-${source.id}`}>{t("出处（可选）")}</label>
              <input id={`source-provenance-${source.id}`} value={draft.provenance} onChange={(event) => setDraft({ ...draft, provenance: event.target.value })} />
            </>
          ) : null}
        </div>
      ) : null}
      <div className="button-row">
        {source.capabilities.can_retry ? (
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={() => void perform(
              () => source.kind === "url" ? retryUrlSource(accessToken, source.id) : retryFileSource(accessToken, source.id),
              "重试来源失败。",
            )}
          >{t("重试处理")}</button>
        ) : null}
        {source.capabilities.can_cancel && source.active_execution ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => void perform(() => cancelExecution(accessToken, source.active_execution!.id), "取消处理失败。")}
          >{t("取消处理")}</button>
        ) : null}
        {source.capabilities.can_delete ? (
          <button
            className="button button--quiet button--quiet-danger"
            type="button"
            disabled={busy}
            onClick={() => void perform(() => deleteTaskCreationSource(accessToken, source.id), "删除来源失败。")}
          >{t("删除来源")}</button>
        ) : null}
      </div>
      </div> : null}
    </article>
  );
}

export function TaskCreationSession({
  accessToken,
  onCreated,
  onDirtyChange,
}: {
  accessToken: AccessToken;
  onCreated(task: TaskSummary): void;
  onDirtyChange(dirty: boolean): void;
}) {
  const { t, domainMessage } = useInterfaceLocale();
  const [draft, setDraft] = useState<DraftSource>(emptyDraft);
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  // The session id is the only way back to sources already added to it. Held in
  // memory it did not survive a reload, and every source in the abandoned
  // session was stranded on the server with nothing able to reach it.
  const [clientSessionId] = useState(() => {
    const stored = window.localStorage.getItem(CREATION_SESSION_KEY);
    if (stored) return stored;
    const created = crypto.randomUUID();
    window.localStorage.setItem(CREATION_SESSION_KEY, created);
    return created;
  });
  const [mode, setMode] = useState<"pasted" | "url" | "file">("pasted");
  // Locked until proven otherwise, so a slow answer never briefly offers a 来源
  // kind the server is about to refuse.
  const account = useQuery({
    queryKey: ["account", accessToken],
    queryFn: () => getAccount(accessToken),
  });
  const locked = !account.data?.is_paying_user;
  const [session, setSession] = useState<TaskCreationSessionResponse | null>(null);
  const [editingSourceIds, setEditingSourceIds] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);
  // Never cleared by anything but the user. Not by a 来源 changing, and not by
  // pressing 提炼主题 again.
  const [theme, setTheme] = useState("");
  const sourceCount = session?.source_count ?? 0;
  const dirty =
    sourceCount > 0 || Boolean(theme || url || file || Object.values(draft).some(Boolean));

  const refresh = useCallback(async () => {
    setSession(await getTaskCreationSession(accessToken, clientSessionId));
  }, [accessToken, clientSessionId]);

  useEffect(() => {
    void refresh().catch(() => setError("无法读取创建会话，请重试。"));
  }, [refresh]);

  useEffect(() => {
    if (!session?.sources.some((source) => source.status === "processing")) return;
    let stopped = false;
    let timer: number;
    const poll = async () => {
      try {
        await refresh();
        setError(null);
      } catch {
        setError("暂时无法更新来源状态，正在自动重试。");
      }
      if (!stopped) timer = window.setTimeout(() => void poll(), SOURCE_PREPARATION_POLL_MS);
    };
    timer = window.setTimeout(() => void poll(), SOURCE_PREPARATION_POLL_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [refresh, session]);

  useLayoutEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!dirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);

  async function addSource(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const clientSourceId = crypto.randomUUID();
      if (mode === "pasted") {
        await createPastedSource(accessToken, clientSessionId, clientSourceId, { ...draft, provenance: draft.provenance || null });
        setDraft(emptyDraft);
      } else if (mode === "url") {
        await createUrlSource(accessToken, clientSessionId, clientSourceId, url);
        setUrl("");
      } else if (file) {
        await createFileSource(accessToken, clientSessionId, clientSourceId, file);
        setFile(null);
      }
      await refresh();
      setAdding(false);
      setExpandedSourceId(null);
    } catch (thrown) {
      setError(
        refusalWithoutTiming(thrown) ??
          "添加来源失败。请检查内容是否重复、格式是否支持，或是否已达到三个来源。",
      );
    } finally {
      setBusy(false);
    }
  }

  const canConfirm = Boolean(
    session?.can_confirm
      && editingSourceIds.size === 0
      && !busy
      && theme.length <= MAX_THEME_CHARACTERS,
  );

  const updateEditingSource = useCallback((sourceId: string, editing: boolean) => {
    setEditingSourceIds((current) => {
      if (current.has(sourceId) === editing) return current;
      const next = new Set(current);
      if (editing) next.add(sourceId); else next.delete(sourceId);
      return next;
    });
  }, []);

  async function confirm() {
    if (!session || !canConfirm) return;
    setBusy(true);
    setError(null);
    try {
      const task = await confirmTaskCreationSession(
        accessToken,
        idempotencyKey,
        clientSessionId,
        session.sources.map((source) => source.id),
        // The server still records which version of a warning was in force when
        // the task was created; it is no longer something the writer is asked
        // to click through.
        Object.fromEntries(
          session.sources
            .filter((source) => source.warnings.length > 0)
            .map((source) => [source.id, source.input_version]),
        ),
        theme.trim() || null,
      );
      window.localStorage.removeItem(CREATION_SESSION_KEY);
      onCreated(task);
    } catch (thrown) {
      setError(refusalWithoutTiming(thrown) ?? "创建失败，来源仍保留在此会话中。请重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="creation-session" aria-label={t("任务创建会话")}>
      <p className="section-kicker">{t("添加 1-3 个来源")}</p>

      {/*
        * One list, one spine. A source being added is an item on it like any
        * other, numbered in the place it will occupy, rather than a form that
        * appears somewhere else and has to be related back to the list by eye.
        */}
      <ol className="source-list">
      {session?.sources.map((source, position) => (
        <li key={source.id}>
        <SourceCard
          accessToken={accessToken}
          source={source}
          index={position + 1}
          busy={busy}
          onEditingChange={updateEditingSource}
          onChanged={refresh}
          onBusy={setBusy}
          onError={setError}
          expanded={expandedSourceId === source.id}
          onToggle={() => {
            setExpandedSourceId((current) => current === source.id ? null : source.id);
          }}
        />
        </li>
      ))}

      {adding ? (
        <li>
        <article className="source-operation source-operation--draft">
          <p className="source-operation__summary source-operation__summary--draft">
            <strong>
              <span className="source-operation__index">{sourceCount + 1}</span>
              {t("新来源")}
            </strong>
            <span className="source-operation__pending">{t("尚未添加")}</span>
          </p>
        <form className="creation-form source-operation__editor" onSubmit={(event) => void addSource(event)}>
          <div className="source-kind-tabs" aria-label={t("来源类型")}>
            <button className={`button ${mode === "pasted" ? "" : "button--quiet"}`} type="button" onClick={() => setMode("pasted")}>{t("粘贴文本")}</button>
            {/*
              `aria-disabled` rather than `disabled`. A disabled control leaves
              the tab order and screen readers pass over it, which would hide a
              paid capability from exactly the people who cannot see the lock —
              and a capability nobody can find is one nobody can want.
            */}
            <button
              aria-disabled={locked || undefined}
              aria-describedby={locked ? "source-kinds-locked" : undefined}
              className={`button ${mode === "url" ? "" : "button--quiet"}`}
              type="button"
              onClick={() => { if (!locked) setMode("url"); }}
            >
              {locked ? <Lock size={14} aria-hidden="true" /> : null}{t("公共文章链接")}
            </button>
            <button
              aria-disabled={locked || undefined}
              aria-describedby={locked ? "source-kinds-locked" : undefined}
              className={`button ${mode === "file" ? "" : "button--quiet"}`}
              type="button"
              onClick={() => { if (!locked) setMode("file"); }}
            >
              {locked ? <Lock size={14} aria-hidden="true" /> : null}{t("上传文件")}
            </button>
          </div>
          {locked ? (
            <p className="source-kinds-locked" id="source-kinds-locked">
              {t("公共文章链接与上传文件需购买额度后解锁。")}
              <Link className="button button--quiet" to="/account">{t("购买额度")}</Link>
            </p>
          ) : null}
          {mode === "pasted" ? (
            <>
              <label htmlFor="source-title">{t("来源标题")}</label>
              <input key="pasted-title" id="source-title" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required />
              <label htmlFor="source-body">{t("来源正文")}</label>
              <textarea id="source-body" rows={10} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} required />
              <label htmlFor="source-provenance">{t("出处（可选）")}</label>
              <input id="source-provenance" value={draft.provenance} onChange={(event) => setDraft({ ...draft, provenance: event.target.value })} />
            </>
          ) : mode === "url" ? (
            <><label htmlFor="source-url">{t("来源网址")}</label><input key="url" id="source-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} required /></>
          ) : (
            <>
              <label htmlFor="source-file">{t("来源文件")}</label>
              <input key="file" id="source-file" type="file" accept=".pdf,.docx,.txt,.md,.markdown" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <p className="form-hint">{t("支持 PDF、DOCX、TXT 和 Markdown；扫描件不支持 OCR。")}</p>
            </>
          )}
          <div className="button-row">
            <button className="button" type="submit" disabled={busy || (mode === "file" && !file)}>{busy ? t("正在添加…") : t("添加来源")}</button>
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => setAdding(false)}>{t("取消")}</button>
          </div>
        </form>
        </article>
        </li>
      ) : null}
      </ol>

      {session?.can_add !== false ? (
        !adding ? (
          <button
            className="add-source-button"
            type="button"
            onClick={() => {
              setExpandedSourceId(null);
              setAdding(true);
            }}
          >
            <Plus size={18} aria-hidden="true" /> {t("添加来源")}
          </button>
        ) : null
      ) : <p className="creation-hint">{t("已达到三个来源上限；删除一个来源后可继续添加。")}</p>}

      <ThemeChoice
        accessToken={accessToken}
        clientSessionId={clientSessionId}
        theme={theme}
        onThemeChange={setTheme}
        canPropose={Boolean(session?.can_confirm) && !busy}
        disabledReason={
          sourceCount === 0
            ? "请先添加来源，全部抓取成功后才能提炼主题。"
            : session?.can_confirm
              ? null
              : "请等待所有来源处理完成。"
        }
      />

      {error ? (
        <p role="alert" className="form-error">
          {domainMessage(error)}
          {isCreditRefusal(error) ? <BuyCreditsLink /> : null}
        </p>
      ) : null}
      <div className="button-row">
        <button className="button" type="button" disabled={!canConfirm} onClick={() => void confirm()}>{busy ? t("正在创建…") : t("创建任务")}</button>
        {!canConfirm ? (
          <p className="creation-hint">
            {sourceCount === 0
              ? t("请先添加来源。")
              : busy
                ? t("正在保存来源…")
                : t("请等待所有来源处理完成。")}
          </p>
        ) : null}
      </div>
    </section>
  );
}

import { type FormEvent, useCallback, useEffect, useState } from "react";

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
  replaceFileSource,
  replaceUrlSource,
  retryFileSource,
  retryUrlSource,
  type SessionSourceResponse,
  type SourceInput,
  type TaskCreationSessionResponse,
} from "../api/client";
import type { TaskSummary } from "../auth/state";

type DraftSource = { title: string; body: string; provenance: string };
const emptyDraft: DraftSource = { title: "", body: "", provenance: "" };
const sourceKindLabels = { pasted: "粘贴文本", url: "公共文章链接", file: "上传文件" };
const sourceStatusLabels = {
  processing: "处理中",
  ready: "已就绪",
  warning: "已就绪，有警告",
  failure: "处理失败",
};

function SourceCard({
  accessToken,
  source,
  warningAccepted,
  busy,
  onWarningAccepted,
  onEditingChange,
  onChanged,
  onBusy,
  onError,
}: {
  accessToken: string;
  source: SessionSourceResponse;
  warningAccepted: boolean;
  busy: boolean;
  onWarningAccepted(accepted: boolean): void;
  onEditingChange(sourceId: string, dirty: boolean): void;
  onChanged(): Promise<void>;
  onBusy(busy: boolean): void;
  onError(message: string | null): void;
}) {
  const [draft, setDraft] = useState<DraftSource>({
    title: source.title ?? "",
    body: source.body ?? "",
    provenance: source.provenance ?? "",
  });
  const [replacementUrl, setReplacementUrl] = useState("");
  const editing = draft.title !== (source.title ?? "")
    || draft.body !== (source.body ?? "")
    || draft.provenance !== (source.provenance ?? "")
    || replacementUrl.length > 0;

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
      "保存来源失败，请重试。",
    );
  }

  return (
    <article className={`source-operation source-operation--${source.status}`}>
      <div className="source-operation__status">
        <strong>{sourceKindLabels[source.kind]} · {source.title || "未命名来源"}</strong>
        <span>{sourceStatusLabels[source.status]}</span>
      </div>
      {source.failure ? <p role="alert" className="form-error">{source.failure.message}</p> : null}
      {source.warnings.map((warning) => <p className="warning" key={warning.code}>{warning.message}</p>)}
      {source.warnings.length > 0 ? (
        <label>
          <input
            type="checkbox"
            checked={warningAccepted}
            onChange={(event) => onWarningAccepted(event.target.checked)}
          />
          我已检查并接受此来源的警告
        </label>
      ) : null}
      {source.capabilities.can_edit ? (
        <div className="creation-form">
          <label htmlFor={`source-title-${source.id}`}>来源标题</label>
          <input id={`source-title-${source.id}`} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
          <label htmlFor={`source-body-${source.id}`}>来源正文</label>
          <textarea id={`source-body-${source.id}`} rows={8} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} />
          <label htmlFor={`source-provenance-${source.id}`}>出处（可选）</label>
          <input id={`source-provenance-${source.id}`} value={draft.provenance} onChange={(event) => setDraft({ ...draft, provenance: event.target.value })} />
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => void save()}>保存此来源</button>
        </div>
      ) : null}
      {source.capabilities.can_replace && source.kind === "url" ? (
        <div className="creation-form">
          <label htmlFor={`replacement-url-${source.id}`}>替换网址</label>
          <input id={`replacement-url-${source.id}`} type="url" value={replacementUrl} onChange={(event) => setReplacementUrl(event.target.value)} />
          <button
            className="button button--quiet"
            type="button"
            disabled={busy || !replacementUrl}
            onClick={() => void perform(() => replaceUrlSource(accessToken, source.id, replacementUrl), "替换网址失败，请重试。")}
          >替换网址</button>
        </div>
      ) : null}
      {source.capabilities.can_replace && source.kind === "file" ? (
        <label className="button button--quiet">
          替换文件
          <input
            hidden
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void perform(() => replaceFileSource(accessToken, source.id, file), "替换文件失败，请重试。");
            }}
          />
        </label>
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
          >重试处理</button>
        ) : null}
        {source.capabilities.can_cancel && source.active_execution ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => void perform(() => cancelExecution(accessToken, source.active_execution!.id), "取消处理失败。")}
          >取消处理</button>
        ) : null}
        {source.capabilities.can_delete ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => void perform(() => deleteTaskCreationSource(accessToken, source.id), "删除来源失败。")}
          >删除来源</button>
        ) : null}
      </div>
    </article>
  );
}

export function TaskCreationSession({
  accessToken,
  onCreated,
  onClose,
  onDirtyChange,
}: {
  accessToken: string;
  onCreated(task: TaskSummary): void;
  onClose(): void;
  onDirtyChange(dirty: boolean): void;
}) {
  const [draft, setDraft] = useState<DraftSource>(emptyDraft);
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [clientSessionId] = useState(() => crypto.randomUUID());
  const [mode, setMode] = useState<"pasted" | "url" | "file">("pasted");
  const [session, setSession] = useState<TaskCreationSessionResponse | null>(null);
  const [acceptedWarningVersions, setAcceptedWarningVersions] = useState<Map<string, number>>(() => new Map());
  const [editingSourceIds, setEditingSourceIds] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceCount = session?.source_count ?? 0;
  const dirty = sourceCount > 0 || Boolean(url || file || Object.values(draft).some(Boolean));

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
      if (!stopped) timer = window.setTimeout(() => void poll(), 750);
    };
    timer = window.setTimeout(() => void poll(), 750);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [refresh, session]);

  useEffect(() => {
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
    } catch {
      setError("添加来源失败。请检查内容是否重复、格式是否支持，或是否已达到三个来源。");
    } finally {
      setBusy(false);
    }
  }

  const warningSourceIds = session?.sources.filter((source) => source.warnings.length > 0).map((source) => source.id) ?? [];
  const warningsAccepted = session?.sources
    .filter((source) => source.warnings.length > 0)
    .every((source) => acceptedWarningVersions.get(source.id) === source.input_version) ?? true;
  const canConfirm = Boolean(
    session?.can_confirm && warningsAccepted && editingSourceIds.size === 0 && !busy,
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
        Object.fromEntries(
          warningSourceIds.map((sourceId) => [sourceId, acceptedWarningVersions.get(sourceId)!]),
        ),
      );
      onCreated(task);
      onClose();
    } catch {
      setError("创建失败，来源仍保留在此会话中。请重试。");
    } finally {
      setBusy(false);
    }
  }

  const close = () => {
    if (!dirty || window.confirm("未完成的创建内容不会保存，确定离开吗？")) onClose();
  };

  return (
    <section className="creation-session" aria-label="任务创建会话">
      <div className="creation-session__heading">
        <div><p className="section-kicker">一个任务可保留 1–3 个来源</p><h3>整理任务来源</h3></div>
        <button className="button button--quiet" type="button" onClick={close}>关闭</button>
      </div>

      {session?.sources.map((source) => (
        <SourceCard
          key={source.id}
          accessToken={accessToken}
          source={source}
          warningAccepted={acceptedWarningVersions.get(source.id) === source.input_version}
          busy={busy}
          onWarningAccepted={(accepted) => setAcceptedWarningVersions((current) => {
            const next = new Map(current);
            if (accepted) next.set(source.id, source.input_version); else next.delete(source.id);
            return next;
          })}
          onEditingChange={updateEditingSource}
          onChanged={refresh}
          onBusy={setBusy}
          onError={setError}
        />
      ))}

      {session?.can_add !== false ? (
        <form className="creation-form" onSubmit={(event) => void addSource(event)}>
          <div className="source-kind-tabs" aria-label="来源类型">
            <button className={`button ${mode === "pasted" ? "" : "button--quiet"}`} type="button" onClick={() => setMode("pasted")}>粘贴文本</button>
            <button className={`button ${mode === "url" ? "" : "button--quiet"}`} type="button" onClick={() => setMode("url")}>公共文章链接</button>
            <button className={`button ${mode === "file" ? "" : "button--quiet"}`} type="button" onClick={() => setMode("file")}>上传文件</button>
          </div>
          {mode === "pasted" ? (
            <>
              <label htmlFor="source-title">来源标题</label>
              <input key="pasted-title" id="source-title" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required />
              <label htmlFor="source-body">来源正文</label>
              <textarea id="source-body" rows={10} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} required />
              <label htmlFor="source-provenance">出处（可选）</label>
              <input id="source-provenance" value={draft.provenance} onChange={(event) => setDraft({ ...draft, provenance: event.target.value })} />
            </>
          ) : mode === "url" ? (
            <><label htmlFor="source-url">来源网址</label><input key="url" id="source-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} required /></>
          ) : (
            <>
              <label htmlFor="source-file">来源文件</label>
              <input key="file" id="source-file" type="file" accept=".pdf,.docx,.txt,.md,.markdown" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <p className="section-kicker">支持 PDF、DOCX、TXT 和 Markdown；扫描件不支持 OCR。</p>
            </>
          )}
          <button className="button" type="submit" disabled={busy || (mode === "file" && !file)}>{busy ? "正在添加…" : "添加来源"}</button>
        </form>
      ) : <p className="section-kicker">已达到三个来源上限；删除一个来源后可继续添加。</p>}

      {error ? <p role="alert" className="form-error">{error}</p> : null}
      <div className="button-row">
        <button className="button" type="button" disabled={!canConfirm} onClick={() => void confirm()}>{busy ? "正在创建…" : "确认并创建任务"}</button>
        {!canConfirm ? (
          <p className="section-kicker">
            {sourceCount === 0
              ? "请先添加来源。"
              : editingSourceIds.size > 0
                ? "请先保存所有来源编辑。"
                : !session?.can_confirm
                ? "请等待所有来源处理完成。"
                : "请接受所有来源警告。"}
          </p>
        ) : null}
      </div>
    </section>
  );
}

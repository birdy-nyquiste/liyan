import { type FormEvent, useEffect, useState } from "react";

import {
  confirmTaskCreation,
  prepareTaskSource,
  type PreparedSourceResponse,
} from "../api/client";
import type { TaskSummary } from "../auth/state";
import { FileSourcePanel } from "./FileSourcePanel";
import { UrlSourcePanel } from "./UrlSourcePanel";

type DraftSource = { title: string; body: string; provenance: string };
const emptyDraft: DraftSource = { title: "", body: "", provenance: "" };

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
  const [prepared, setPrepared] = useState<PreparedSourceResponse | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [clientSessionId] = useState(() => crypto.randomUUID());
  const [mode, setMode] = useState<"paste" | "url" | "file">("paste");
  const [urlDirty, setUrlDirty] = useState(false);
  const [fileDirty, setFileDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty =
    prepared !== null ||
    urlDirty ||
    fileDirty ||
    Object.values(draft).some((value) => value.length > 0);

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

  async function preview(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await prepareTaskSource(accessToken, {
        title: draft.title,
        body: draft.body,
        provenance: draft.provenance || null,
      });
      setDraft({
        title: result.source.title,
        body: result.source.body,
        provenance: result.source.provenance ?? "",
      });
      setPrepared(result);
    } catch {
      setError("请填写来源标题和正文后再预览。");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!prepared) return;
    setBusy(true);
    setError(null);
    try {
      const task = await confirmTaskCreation(accessToken, idempotencyKey, prepared.source);
      onCreated(task);
      onClose();
    } catch {
      setError("创建失败，内容仍保留在此页面。请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function prepareExtractedSource(source: {
    title: string;
    body: string;
    provenance?: string | null;
  }) {
    setBusy(true);
    setError(null);
    try {
      const result = await prepareTaskSource(accessToken, source);
      setDraft({
        title: result.source.title,
        body: result.source.body,
        provenance: result.source.provenance ?? "",
      });
      setPrepared(result);
    } catch {
      setError("无法准备此来源，请检查提取内容后重试。");
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
        <div>
          <p className="section-kicker">仅保留在当前浏览器页面</p>
          <h3>
            {prepared
              ? "确认来源"
              : mode === "url"
                ? "提取公共文章"
                : mode === "file"
                  ? "解析上传文件"
                  : "粘贴一个来源"}
          </h3>
        </div>
        <button className="button button--quiet" type="button" onClick={close}>
          关闭
        </button>
      </div>
      {!prepared ? (
        <div className="source-kind-tabs" aria-label="来源类型">
          <button
            className={`button ${mode === "paste" ? "" : "button--quiet"}`}
            type="button"
            onClick={() => setMode("paste")}
          >
            粘贴文本
          </button>
          <button
            className={`button ${mode === "url" ? "" : "button--quiet"}`}
            type="button"
            onClick={() => setMode("url")}
          >
            公共文章链接
          </button>
          <button
            className={`button ${mode === "file" ? "" : "button--quiet"}`}
            type="button"
            onClick={() => setMode("file")}
          >
            上传文件
          </button>
        </div>
      ) : null}
      {prepared ? (
        <div className="source-preview">
          <h4>{prepared.source.title}</h4>
          <pre>{prepared.source.body}</pre>
          <p>{prepared.source.provenance ?? "未填写出处"}</p>
          {prepared.warnings.map((warning) => (
            <p className="warning" key={warning.code}>
              {warning.code === "short_body"
                ? "正文较短，请确认内容完整。"
                : "未填写出处，仍可继续创建。"}
            </p>
          ))}
          {error ? (
            <p role="alert" className="form-error">{error}</p>
          ) : null}
          <div className="button-row">
            <button
              className="button button--quiet"
              type="button"
              onClick={() => setPrepared(null)}
            >
              返回编辑
            </button>
            <button className="button" type="button" disabled={busy} onClick={() => void confirm()}>
              {busy ? "正在创建…" : "确认并创建任务"}
            </button>
          </div>
        </div>
      ) : null}
      <div hidden={prepared !== null || mode !== "url"}>
        <UrlSourcePanel
          accessToken={accessToken}
          clientSessionId={clientSessionId}
          onDirtyChange={setUrlDirty}
          onPrepared={(source) => void prepareExtractedSource(source)}
        />
      </div>
      <div hidden={prepared !== null || mode !== "file"}>
        <FileSourcePanel
          accessToken={accessToken}
          clientSessionId={clientSessionId}
          onDirtyChange={setFileDirty}
          onPrepared={(source) => void prepareExtractedSource(source)}
        />
      </div>
      <form
        className="creation-form"
        hidden={prepared !== null || mode !== "paste"}
        onSubmit={(event) => void preview(event)}
      >
        <label htmlFor="source-title">来源标题</label>
        <input
          id="source-title"
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.target.value })}
          required
        />
        <label htmlFor="source-body">来源正文</label>
        <textarea
          id="source-body"
          rows={12}
          value={draft.body}
          onChange={(event) => setDraft({ ...draft, body: event.target.value })}
          required
        />
        <label htmlFor="source-provenance">出处（可选）</label>
        <input
          id="source-provenance"
          value={draft.provenance}
          onChange={(event) => setDraft({ ...draft, provenance: event.target.value })}
        />
        {error ? (
          <p role="alert" className="form-error">{error}</p>
        ) : null}
        <button className="button" type="submit" disabled={busy}>
          {busy ? "正在整理…" : "预览来源"}
        </button>
      </form>
    </section>
  );
}

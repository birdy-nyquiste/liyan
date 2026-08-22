import type { FormEvent } from "react";

import type { SourceInput, UrlSourceResponse } from "../api/client";
import { useUrlSource } from "./useUrlSource";

type SourceStatus = UrlSourceResponse["status"];
type ExecutionStatus = NonNullable<UrlSourceResponse["active_execution"]>["status"];

const sourceStatusLabels: Record<SourceStatus, string> = {
  processing: "正在提取",
  ready: "提取完成",
  warning: "提取完成，有警告",
  failure: "提取失败",
};
const executionStatusLabels: Record<ExecutionStatus, string> = {
  queued: "排队中",
  running: "执行中",
  cancel_requested: "正在取消",
  cancelled: "已取消",
  failed: "失败",
  stale: "已失效",
  succeeded: "已完成",
};

export function UrlSourcePanel({
  accessToken,
  clientSessionId,
  onDirtyChange,
  onPrepared,
}: {
  accessToken: string;
  clientSessionId: string;
  onDirtyChange(dirty: boolean): void;
  onPrepared(source: SourceInput): void;
}) {
  const state = useUrlSource({ accessToken, clientSessionId, onDirtyChange, onPrepared });
  const {
    url, setUrl, source, title, setTitle, body, setBody, provenance, setProvenance,
    error, busy, start, retry, replace, acceptSource, cancel,
  } = state;

  const prepared = source?.status === "ready" || source?.status === "warning";
  return (
    <div className="url-source-panel">
      <form className="creation-form" onSubmit={(event: FormEvent) => { event.preventDefault(); void start(); }}>
        <label htmlFor="source-url">来源网址</label>
        <input
          id="source-url"
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
        {!source ? (
          <button className="button" type="submit" disabled={busy}>
            {busy ? "正在提交…" : "开始提取"}
          </button>
        ) : null}
      </form>

      {source ? (
        <div className={`source-operation source-operation--${source.status}`}>
          <div className="source-operation__status">
            <strong>{sourceStatusLabels[source.status]}</strong>
            {source.active_execution ? (
              <span>
                尝试 {source.active_execution.attempt} · {executionStatusLabels[source.active_execution.status]}
              </span>
            ) : null}
          </div>
          {source.failure ? <p role="alert" className="form-error">{source.failure.message}</p> : null}
          {source.warnings.map((warning) => <p className="warning" key={warning.code}>{warning.message}</p>)}
          {prepared ? (
            <div className="creation-form">
              <label htmlFor="url-source-title">来源标题</label>
              <input id="url-source-title" value={title} onChange={(event) => setTitle(event.target.value)} />
              <label htmlFor="url-source-body">来源正文</label>
              <textarea id="url-source-body" rows={12} value={body} onChange={(event) => setBody(event.target.value)} />
              <label htmlFor="url-source-provenance">出处（可选）</label>
              <input id="url-source-provenance" value={provenance} onChange={(event) => setProvenance(event.target.value)} />
              <button className="button" type="button" disabled={busy} onClick={() => void acceptSource()}>
                使用此来源
              </button>
            </div>
          ) : null}
          <div className="button-row">
            {source.capabilities.can_retry ? (
              <button className="button" type="button" disabled={busy} onClick={() => void retry()}>重试提取</button>
            ) : null}
            {source.capabilities.can_replace ? (
              <button className="button button--quiet" type="button" disabled={busy} onClick={() => void replace()}>替换网址</button>
            ) : null}
            {source.capabilities.can_cancel ? (
              <button className="button button--quiet" type="button" disabled={busy} onClick={() => void cancel()}>取消提取</button>
            ) : null}
          </div>
        </div>
      ) : null}
      {error ? <p role="alert" className="form-error">{error}</p> : null}
    </div>
  );
}

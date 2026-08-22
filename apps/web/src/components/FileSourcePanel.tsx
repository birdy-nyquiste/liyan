import type { FileSourceResponse, SourceInput } from "../api/client";
import { useFileSource } from "./useFileSource";

type ExecutionStatus = NonNullable<FileSourceResponse["active_execution"]>["status"];

const executionStatusLabels: Record<ExecutionStatus, string> = {
  queued: "排队中",
  running: "执行中",
  cancel_requested: "正在取消",
  cancelled: "已取消",
  failed: "失败",
  stale: "已失效",
  succeeded: "已完成",
};

export function FileSourcePanel({
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
  const state = useFileSource({ accessToken, clientSessionId, onDirtyChange, onPrepared });
  const {
    file,
    setFile,
    source,
    title,
    setTitle,
    body,
    setBody,
    provenance,
    setProvenance,
    error,
    busy,
    start,
    retry,
    acceptSource,
    cancel,
  } = state;
  const prepared = source?.status === "ready" || source?.status === "warning";
  const statusLabel = source?.status === "processing"
    ? "正在解析"
    : source?.status === "failure"
      ? "解析失败"
      : source?.status === "warning"
        ? "解析完成，有警告"
        : "解析完成";

  return (
    <div className="url-source-panel">
      <div className="creation-form">
        <label htmlFor="source-file">来源文件</label>
        <input
          id="source-file"
          type="file"
          accept=".pdf,.docx,.txt,.md,.markdown"
          disabled={source !== null}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
        <p className="section-kicker">支持 PDF、DOCX、TXT 和 Markdown；扫描件不支持 OCR。</p>
        {!source ? (
          <button
            className="button"
            type="button"
            disabled={busy || file === null}
            onClick={() => void start()}
          >
            {busy ? "正在上传…" : "开始解析"}
          </button>
        ) : null}
      </div>

      {source ? (
        <div className={`source-operation source-operation--${source.status}`}>
          <div className="source-operation__status">
            <strong>{statusLabel}</strong>
            {source.active_execution ? (
              <span>
                尝试 {source.active_execution.attempt} · {executionStatusLabels[source.active_execution.status]}
              </span>
            ) : null}
          </div>
          <p>{source.filename} · {source.size_bytes} 字节</p>
          {source.failure ? <p role="alert" className="form-error">{source.failure.message}</p> : null}
          {source.warnings.map((warning) => <p className="warning" key={warning.code}>{warning.message}</p>)}
          {prepared ? (
            <div className="creation-form">
              <label htmlFor="file-source-title">来源标题</label>
              <input id="file-source-title" value={title} onChange={(event) => setTitle(event.target.value)} />
              <label htmlFor="file-source-body">来源正文</label>
              <textarea id="file-source-body" rows={12} value={body} onChange={(event) => setBody(event.target.value)} />
              <label htmlFor="file-source-provenance">出处（可选）</label>
              <input id="file-source-provenance" value={provenance} onChange={(event) => setProvenance(event.target.value)} />
              <button className="button" type="button" disabled={busy} onClick={() => void acceptSource()}>
                使用此来源
              </button>
            </div>
          ) : null}
          <div className="button-row">
            {source.capabilities.can_retry ? (
              <button className="button" type="button" disabled={busy} onClick={() => void retry()}>重试解析</button>
            ) : null}
            {source.capabilities.can_cancel ? (
              <button className="button button--quiet" type="button" disabled={busy} onClick={() => void cancel()}>取消解析</button>
            ) : null}
          </div>
        </div>
      ) : null}
      {error ? <p role="alert" className="form-error">{error}</p> : null}
    </div>
  );
}

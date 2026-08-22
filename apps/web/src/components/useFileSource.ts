import { useEffect, useRef, useState } from "react";

import {
  cancelExecution,
  createFileSource,
  editFileSourceContent,
  getFileSource,
  retryFileSource,
  type FileSourceResponse,
  type SourceInput,
} from "../api/client";

const activeExecutionStatuses = new Set(["queued", "running", "cancel_requested"]);

export function useFileSource({
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
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState<FileSourceResponse | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [provenance, setProvenance] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const clientSourceId = useRef(crypto.randomUUID());

  useEffect(() => onDirtyChange(file !== null || source !== null), [file, onDirtyChange, source]);
  useEffect(
    () => () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      onDirtyChange(false);
    },
    [onDirtyChange],
  );

  function applySource(next: FileSourceResponse) {
    setSource(next);
    if (next.title !== null) setTitle(next.title);
    if (next.body !== null) setBody(next.body);
    if (next.provenance !== null) setProvenance(next.provenance);
  }

  async function poll(sourceId: string): Promise<void> {
    try {
      const next = await getFileSource(accessToken, sourceId);
      applySource(next);
      if (next.active_execution && activeExecutionStatuses.has(next.active_execution.status)) {
        pollTimer.current = window.setTimeout(() => void poll(sourceId), 1000);
      }
    } catch {
      setError("暂时无法读取解析状态，请稍后重试。");
    }
  }

  async function run(action: () => Promise<FileSourceResponse>, message: string) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      applySource(next);
      await poll(next.id);
    } catch {
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  const start = () =>
    file
      ? run(
          () => createFileSource(accessToken, clientSessionId, clientSourceId.current, file),
          "无法上传此文件。请使用 PDF、DOCX、TXT 或 Markdown 后重试。",
        )
      : Promise.resolve();
  const retry = () =>
    source
      ? run(() => retryFileSource(accessToken, source.id), "重试失败，请稍后再试。")
      : Promise.resolve();

  async function acceptSource() {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await editFileSourceContent(accessToken, source.id, {
        title,
        body,
        provenance: provenance || null,
      });
      applySource(updated);
      onPrepared({
        title: updated.title ?? title,
        body: updated.body ?? body,
        provenance: updated.provenance,
      });
    } catch {
      setError("请确认标题和正文后再使用此来源。");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!source?.active_execution) return;
    setBusy(true);
    setError(null);
    try {
      await cancelExecution(accessToken, source.active_execution.id);
      await poll(source.id);
    } catch {
      setError("取消失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return {
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
  };
}

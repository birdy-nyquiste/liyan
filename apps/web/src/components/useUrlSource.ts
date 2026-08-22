import { useEffect, useRef, useState } from "react";

import {
  cancelExecution,
  createUrlSource,
  editUrlSourceContent,
  getUrlSource,
  replaceUrlSource,
  retryUrlSource,
  type SourceInput,
  type UrlSourceResponse,
} from "../api/client";

const activeExecutionStatuses = new Set(["queued", "running", "cancel_requested"]);

export function useUrlSource({
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
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<UrlSourceResponse | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [provenance, setProvenance] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const clientSourceId = useRef(crypto.randomUUID());

  useEffect(() => onDirtyChange(url.length > 0 || source !== null), [onDirtyChange, source, url]);
  useEffect(
    () => () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      onDirtyChange(false);
    },
    [onDirtyChange],
  );

  function applySource(next: UrlSourceResponse) {
    setSource(next);
    if (next.title !== null) setTitle(next.title);
    if (next.body !== null) setBody(next.body);
    if (next.provenance !== null) setProvenance(next.provenance);
  }

  async function poll(sourceId: string): Promise<void> {
    try {
      const next = await getUrlSource(accessToken, sourceId);
      applySource(next);
      if (next.active_execution && activeExecutionStatuses.has(next.active_execution.status)) {
        pollTimer.current = window.setTimeout(() => void poll(sourceId), 1000);
      }
    } catch {
      setError("暂时无法读取提取状态，请稍后重试。");
    }
  }

  async function run(action: () => Promise<UrlSourceResponse>, message: string) {
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
    run(
      () => createUrlSource(accessToken, clientSessionId, clientSourceId.current, url),
      "无法开始提取，请检查网址后重试。",
    );
  const retry = () =>
    source
      ? run(() => retryUrlSource(accessToken, source.id), "重试失败，请稍后再试。")
      : Promise.resolve();
  const replace = () =>
    source
      ? run(() => replaceUrlSource(accessToken, source.id, url), "替换失败，请检查网址后重试。")
      : Promise.resolve();

  async function acceptSource() {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await editUrlSourceContent(accessToken, source.id, {
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
    url,
    setUrl,
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
    replace,
    acceptSource,
    cancel,
  };
}

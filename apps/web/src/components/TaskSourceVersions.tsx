import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createPastedSource,
  createFileSource,
  createSourceEditSession,
  createUrlSource,
  deleteTaskCreationSource,
  discardSourceEditSession,
  listTaskVersions,
  getTaskCreationSession,
  restoreTaskVersion,
  saveSourceEditSession,
  type SessionSourceResponse,
  type TaskVersionSnapshot,
  type VersionSource,
} from "../api/client";

type DraftSource = {
  key: string;
  sourceId?: string;
  baseRevisionId?: string;
  prepared?: Pick<
    SessionSourceResponse,
    "id" | "input_version" | "status" | "title" | "body" | "provenance" | "warnings"
  >;
  title: string;
  body: string;
  provenance: string;
  warningAccepted: boolean;
  preparedKind?: "pasted" | "url" | "file";
};

const LOAD_FAILED = "任务版本加载失败，请稍后重试。";
const EDIT_FAILED = "暂时无法进入来源编辑，请稍后重试。";
const SAVE_FAILED = "来源修改保存失败；当前任务版本没有改变。";
const RESTORE_FAILED = "任务版本恢复失败，请稍后重试。";
const ignoreEditingChange = () => undefined;

function draftOf(source: VersionSource): DraftSource {
  return {
    key: source.source_id,
    sourceId: source.source_id,
    baseRevisionId: source.id,
    title: source.title,
    body: source.body,
    provenance: source.provenance ?? "",
    warningAccepted: true,
  };
}

export function TaskSourceVersions({
  accessToken,
  taskId,
  onVersionSelected,
  onCurrentVersionChanged,
  onEditingChange = ignoreEditingChange,
}: {
  accessToken: string;
  taskId: string;
  onVersionSelected(versionId: string): void;
  onCurrentVersionChanged(version: TaskVersionSnapshot): void;
  onEditingChange?(editing: boolean): void;
}) {
  const [versions, setVersions] = useState<TaskVersionSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editSessionId, setEditSessionId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newProvenance, setNewProvenance] = useState("");
  const [newMode, setNewMode] = useState<"pasted" | "url" | "file">("pasted");
  const [newUrl, setNewUrl] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [replaceKey, setReplaceKey] = useState<string | null>(null);
  const [saveIdempotencyKey, setSaveIdempotencyKey] = useState<string | null>(null);
  const editingChangeRef = useRef(onEditingChange);

  useEffect(() => {
    editingChangeRef.current = onEditingChange;
  }, [onEditingChange]);

  const load = useCallback(async () => {
    try {
      const history = await listTaskVersions(accessToken, taskId);
      setVersions(history.items);
      setSelectedId((current) => current ?? history.items[0]?.id ?? null);
      if (history.items[0]) onVersionSelected(history.items[0].id);
      setError(null);
    } catch {
      setError(LOAD_FAILED);
    }
  }, [accessToken, onVersionSelected, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!editSessionId) return;
    editingChangeRef.current(true);
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    const discardOnCommittedNavigation = () => {
      void discardSourceEditSession(accessToken, editSessionId, true).catch(() => undefined);
    };
    window.addEventListener("beforeunload", warn);
    window.addEventListener("pagehide", discardOnCommittedNavigation);
    return () => {
      window.removeEventListener("beforeunload", warn);
      window.removeEventListener("pagehide", discardOnCommittedNavigation);
      void discardSourceEditSession(accessToken, editSessionId).catch(() => undefined);
      editingChangeRef.current(false);
    };
  }, [accessToken, editSessionId]);

  useEffect(() => {
    if (!editSessionId || !drafts.some((source) => source.prepared?.status === "processing")) {
      return;
    }
    const timer = window.setTimeout(() => {
      void getTaskCreationSession(accessToken, editSessionId).then((session) => {
        const byId = new Map(session.sources.map((source) => [source.id, source]));
        setDrafts((current) => current.map((draft) => {
          const prepared = draft.prepared && byId.get(draft.prepared.id);
          return prepared
            ? {
                ...draft,
                prepared,
                title: prepared.title ?? draft.title,
                body: prepared.body ?? draft.body,
                provenance: prepared.provenance ?? draft.provenance,
              }
            : draft;
        }));
      });
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [accessToken, drafts, editSessionId]);

  const selected = useMemo(
    () => versions.find((version) => version.id === selectedId) ?? null,
    [selectedId, versions],
  );

  async function beginEditing() {
    setBusy(true);
    try {
      const edit = await createSourceEditSession(accessToken, taskId);
      setEditSessionId(edit.id);
      setSaveIdempotencyKey(crypto.randomUUID());
      setDrafts(edit.base_version.sources.map(draftOf));
      setError(null);
    } catch {
      setError(EDIT_FAILED);
    } finally {
      setBusy(false);
    }
  }

  function updateDraft(key: string, update: Partial<DraftSource>) {
    setDrafts((current) =>
      current.map((source) => (source.key === key ? { ...source, ...update } : source)),
    );
  }

  async function stageInput(event: FormEvent) {
    event.preventDefault();
    if (!editSessionId || (drafts.length >= 3 && replaceKey === null)) return;
    setBusy(true);
    try {
      const clientSourceId = crypto.randomUUID();
      const replaced = drafts.find((source) => source.key === replaceKey);
      if (replaced?.prepared) {
        await deleteTaskCreationSource(accessToken, replaced.prepared.id);
      }
      const prepared = newMode === "pasted"
        ? await createPastedSource(accessToken, editSessionId, clientSourceId, {
            title: newTitle,
            body: newBody,
            provenance: newProvenance || null,
          })
        : newMode === "url"
          ? await createUrlSource(accessToken, editSessionId, clientSourceId, newUrl)
          : await createFileSource(accessToken, editSessionId, clientSourceId, newFile!);
      const staged = {
        key: prepared.id,
        prepared,
        title: prepared.title ?? (newMode === "url" ? newUrl : newFile?.name ?? newTitle),
        body: prepared.body ?? "",
        provenance: prepared.provenance ?? "",
        warningAccepted: prepared.warnings.length === 0,
        preparedKind: newMode,
      };
      setDrafts((current) => replaceKey
        ? current.map((source) => source.key === replaceKey
            ? {
                ...staged,
                key: source.key,
                sourceId: source.sourceId,
                baseRevisionId: source.baseRevisionId,
              }
            : source)
        : [...current, staged]);
      setNewTitle("");
      setNewBody("");
      setNewProvenance("");
      setNewUrl("");
      setNewFile(null);
      setReplaceKey(null);
      setError(null);
    } catch {
      setError("新增来源失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!editSessionId) return;
    setBusy(true);
    try {
      const saved = await saveSourceEditSession(accessToken, editSessionId, {
        idempotency_key: saveIdempotencyKey ?? crypto.randomUUID(),
        sources: drafts.map((source) =>
          source.sourceId
            ? {
                source_id: source.sourceId,
                base_revision_id: source.baseRevisionId ?? null,
                prepared_source_id: source.prepared?.id ?? null,
                content: {
                  title: source.title,
                  body: source.body,
                  provenance: source.provenance || null,
                },
              }
            : {
                prepared_source_id: source.prepared?.id ?? null,
                content: {
                  title: source.title,
                  body: source.body,
                  provenance: source.provenance || null,
                },
              },
        ),
        accepted_warning_versions: Object.fromEntries(
          drafts
            .filter((source) => source.prepared?.warnings.length)
            .map((source) => [source.prepared!.id, source.prepared!.input_version]),
        ),
      });
      const history = await listTaskVersions(accessToken, taskId);
      setVersions(history.items);
      setSelectedId(saved.id);
      setEditSessionId(null);
      setSaveIdempotencyKey(null);
      setDrafts([]);
      onVersionSelected(saved.id);
      onCurrentVersionChanged(saved);
      setError(null);
    } catch {
      setError(SAVE_FAILED);
    } finally {
      setBusy(false);
    }
  }

  const stagedReady = drafts.every((source) =>
    !source.prepared
    || (
      ["ready", "warning"].includes(source.prepared.status)
      && (source.prepared.warnings.length === 0 || source.warningAccepted)
    ),
  );
  const hasChanges = selected !== null && (
    drafts.length !== selected.sources.length
    || drafts.some((draft, index) => {
      const original = selected.sources[index];
      return draft.prepared !== undefined
        || original === undefined
        || draft.sourceId !== original.source_id
        || draft.title !== original.title
        || draft.body !== original.body
        || draft.provenance !== (original.provenance ?? "");
    })
  );

  async function discard() {
    if (!editSessionId) return;
    if (!window.confirm("未保存的来源修改会被丢弃，确定放弃吗？")) return;
    setBusy(true);
    try {
      await discardSourceEditSession(accessToken, editSessionId);
      setEditSessionId(null);
      setSaveIdempotencyKey(null);
      setDrafts([]);
      setError(null);
    } catch {
      setError("放弃来源修改失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  async function removeDraft(source: DraftSource) {
    if (source.prepared) {
      await deleteTaskCreationSource(accessToken, source.prepared.id).catch(() => undefined);
    }
    setDrafts((current) => current.filter((item) => item.key !== source.key));
  }

  async function restore() {
    if (!selected || !window.confirm(`确定将 V${selected.number} 恢复为当前版本吗？`)) return;
    setBusy(true);
    try {
      const restored = await restoreTaskVersion(
        accessToken,
        taskId,
        selected.id,
        crypto.randomUUID(),
      );
      await load();
      setSelectedId(restored.id);
      onVersionSelected(restored.id);
      onCurrentVersionChanged(restored);
      setError(null);
    } catch {
      setError(RESTORE_FAILED);
    } finally {
      setBusy(false);
    }
  }

  if (!selected) {
    return <p role={error ? "alert" : undefined}>{error ?? "任务版本加载中"}</p>;
  }

  return (
    <section className="source-versions" aria-labelledby={`sources-${taskId}`}>
      <div className="source-versions__heading">
        <div>
          <p className="section-kicker">来源</p>
          <h3 id={`sources-${taskId}`}>
            {selected.is_current ? `当前任务版本 V${selected.number}` : `只读历史 V${selected.number}`}
          </h3>
        </div>
        <label>
          任务版本
          <select
            value={selected.id}
            disabled={editSessionId !== null}
            onChange={(event) => {
              setSelectedId(event.target.value);
              onVersionSelected(event.target.value);
            }}
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                V{version.number}{version.is_current ? "（当前）" : "（历史）"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p role="alert" className="form-error">{error}</p> : null}
      {editSessionId ? (
        <>
          <p className="form-hint">
            当前任务版本仍是 V{selected.number}；保存前的改动不会进入历史。
          </p>
          {drafts.map((source) => (
            <fieldset key={source.key} aria-label={`来源 ${source.title}`}>
              <label>
                来源标题
                <input
                  value={source.title}
                  onChange={(event) => updateDraft(source.key, { title: event.target.value })}
                />
              </label>
              <label>
                来源正文
                <textarea
                  value={source.body}
                  onChange={(event) => updateDraft(source.key, { body: event.target.value })}
                />
              </label>
              <label>
                来源信息
                <input
                  value={source.provenance}
                  onChange={(event) => updateDraft(source.key, { provenance: event.target.value })}
                />
              </label>
              <button
                className="button button--quiet"
                type="button"
                disabled={drafts.length === 1}
                aria-label={`删除来源 ${source.title}`}
                onClick={() => void removeDraft(source)}
              >
                删除来源
              </button>
              <button
                className="button button--quiet"
                type="button"
                aria-label={`替换来源 ${source.title}`}
                onClick={() => setReplaceKey(source.key)}
              >
                替换来源
              </button>
              {source.prepared ? (
                <p className="form-hint">
                  替换输入：{{ processing: "处理中", ready: "已就绪", warning: "已就绪，有警告", failure: "处理失败" }[source.prepared.status]}
                </p>
              ) : null}
              {source.prepared?.warnings.map((warning) => (
                <p className="warning" key={warning.code}>{warning.message}</p>
              ))}
              {source.prepared?.warnings.length ? (
                <label>
                  <input
                    type="checkbox"
                    checked={source.warningAccepted}
                    onChange={(event) => updateDraft(source.key, { warningAccepted: event.target.checked })}
                  />
                  我已检查并接受此来源的警告
                </label>
              ) : null}
            </fieldset>
          ))}
          {drafts.length < 3 || replaceKey ? (
            <form className="source-add-form" onSubmit={(event) => void stageInput(event)}>
              <h4>{replaceKey ? "替换来源" : "新增来源"}</h4>
              <div className="workspace__actions">
                <button type="button" className={`button ${newMode === "pasted" ? "" : "button--quiet"}`} onClick={() => setNewMode("pasted")}>粘贴文本</button>
                <button type="button" className={`button ${newMode === "url" ? "" : "button--quiet"}`} onClick={() => setNewMode("url")}>公共文章链接</button>
                <button type="button" className={`button ${newMode === "file" ? "" : "button--quiet"}`} onClick={() => setNewMode("file")}>上传文件</button>
              </div>
              {newMode === "pasted" ? (
                <>
                  <label>新来源标题<input required value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /></label>
                  <label>新来源正文<textarea required value={newBody} onChange={(event) => setNewBody(event.target.value)} /></label>
                  <label>新来源信息<input value={newProvenance} onChange={(event) => setNewProvenance(event.target.value)} /></label>
                </>
              ) : newMode === "url" ? (
                <label>新来源网址<input type="url" required value={newUrl} onChange={(event) => setNewUrl(event.target.value)} /></label>
              ) : (
                <label>新来源文件<input type="file" required accept=".pdf,.docx,.txt,.md" onChange={(event) => setNewFile(event.target.files?.[0] ?? null)} /></label>
              )}
              <button className="button button--quiet" type="submit" disabled={busy}>
                {replaceKey ? "确认替换" : "添加来源"}
              </button>
              {replaceKey ? <button type="button" className="button button--quiet" onClick={() => setReplaceKey(null)}>取消替换</button> : null}
            </form>
          ) : null}
          <div className="workspace__actions">
            <button className="button" type="button" disabled={busy || !stagedReady || !hasChanges} onClick={() => void save()}>
              保存来源修改
            </button>
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => void discard()}>
              放弃编辑
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="source-version-list">
            {selected.sources.map((source) => (
              <article key={source.id}>
                <h4>{source.title}</h4>
                <p>{source.provenance ?? "未提供来源信息"}</p>
                <pre>{source.body}</pre>
              </article>
            ))}
          </div>
          {selected.capabilities.can_edit ? (
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => void beginEditing()}>
              编辑来源
            </button>
          ) : null}
          {selected.capabilities.can_restore ? (
            <button className="button" type="button" disabled={busy} onClick={() => void restore()}>
              恢复为当前版本
            </button>
          ) : null}
          {selected.capabilities.unavailable_reason ? (
            <p className="form-hint">{selected.capabilities.unavailable_reason}</p>
          ) : null}
        </>
      )}
    </section>
  );
}

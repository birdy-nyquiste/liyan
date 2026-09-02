import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Plus } from "lucide-react";

import { ConfirmDialog } from "./ConfirmDialog";
import { RunningNotice } from "./RunningNotice";

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
  type AccessToken,
} from "../api/client";
import { BuyCreditsLink } from "./BuyCreditsLink";
import { ThemeChoice } from "./ThemeChoice";
import { isCreditRefusal } from "./creditRefusal";
import { EXECUTION_POLL_MS } from "./pollIntervals";
import { useInterfaceLocale } from "../interfaceLocale";

const PREPARED_STATUS_LABELS = {
  processing: "处理中",
  ready: "已就绪",
  warning: "有警告",
  failure: "处理失败",
} as const;

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
  preparedKind?: "pasted" | "url" | "file";
};

const LOAD_FAILED = "版本加载失败，请稍后重试。";
const EDIT_FAILED = "暂时无法进入来源编辑，请稍后重试。";
const SAVE_FAILED = "来源修改保存失败；当前版本没有改变。";
const RESTORE_FAILED = "版本恢复失败，请稍后重试。";
const ignoreEditingChange = () => undefined;

function draftOf(source: VersionSource): DraftSource {
  return {
    key: source.source_id,
    sourceId: source.source_id,
    baseRevisionId: source.id,
    title: source.title,
    body: source.body,
    provenance: source.provenance ?? "",
  };
}

export function TaskSourceVersions({
  accessToken,
  taskId,
  onVersionSelected,
  onCurrentVersionChanged,
  onEditingChange = ignoreEditingChange,
}: {
  accessToken: AccessToken;
  taskId: string;
  onVersionSelected(versionId: string): void;
  onCurrentVersionChanged(version: TaskVersionSnapshot): void;
  onEditingChange?(editing: boolean): void;
}) {
  const { locale, t, domainMessage } = useInterfaceLocale();
  const [versions, setVersions] = useState<TaskVersionSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editSessionId, setEditSessionId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftSource[]>([]);
  // The 主题 as edited. Null means "not editing"; the empty string is a 主题 the
  // user cleared, which is a save like any other and is how 立言 is reopened when
  // a 主题 report will not succeed.
  const [themeDraft, setThemeDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newProvenance, setNewProvenance] = useState("");
  const [newMode, setNewMode] = useState<"pasted" | "url" | "file">("pasted");
  const [newUrl, setNewUrl] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [replaceKey, setReplaceKey] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<"discard" | "restore" | null>(null);
  const [openSourceKey, setOpenSourceKey] = useState<string | null>(null);
  const [saveIdempotencyKey, setSaveIdempotencyKey] = useState<string | null>(null);
  const editingChangeRef = useRef(onEditingChange);
  // Callers pass fresh closures on every render. Holding them in refs keeps `load`
  // stable, so mounting reads the version list once instead of on every render.
  const selectedChangeRef = useRef(onVersionSelected);
  const currentChangeRef = useRef(onCurrentVersionChanged);
  const notifiedSelectionRef = useRef<string | null>(null);

  useEffect(() => {
    editingChangeRef.current = onEditingChange;
    selectedChangeRef.current = onVersionSelected;
    currentChangeRef.current = onCurrentVersionChanged;
  }, [onEditingChange, onVersionSelected, onCurrentVersionChanged]);

  // Announce a selection only when it actually changes; re-announcing the same
  // version makes callers discard state they derived from it.
  const announceSelection = useCallback((versionId: string) => {
    if (notifiedSelectionRef.current === versionId) return;
    notifiedSelectionRef.current = versionId;
    selectedChangeRef.current(versionId);
  }, []);

  const load = useCallback(async () => {
    try {
      const history = await listTaskVersions(accessToken, taskId);
      setVersions(history.items);
      setSelectedId((current) => current ?? history.items[0]?.id ?? null);
      if (history.items[0]) announceSelection(history.items[0].id);
      setError(null);
    } catch {
      setError(LOAD_FAILED);
    }
  }, [accessToken, announceSelection, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  /*
    Whether a save has been sent for the session being torn down.

    Leaving this pane discards the editing session, which is the whole point:
    an unfinished 来源编辑会话 is deliberately unrecoverable. But a save is not
    an unfinished session, and the two used to race — pressing 保存修改 and then
    switching tabs unmounted this pane, the discard reached the server first,
    and the save was refused against a session that no longer existed. The
    writer's changes were gone and the screen showed the version they had
    before, with nothing saying why.
  */
  const savingRef = useRef(false);

  useEffect(() => {
    if (!editSessionId) return;
    editingChangeRef.current(true);
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    const discardOnCommittedNavigation = () => {
      if (savingRef.current) return;
      void discardSourceEditSession(accessToken, editSessionId, true).catch(() => undefined);
    };
    window.addEventListener("beforeunload", warn);
    window.addEventListener("pagehide", discardOnCommittedNavigation);
    return () => {
      window.removeEventListener("beforeunload", warn);
      window.removeEventListener("pagehide", discardOnCommittedNavigation);
      if (!savingRef.current) {
        void discardSourceEditSession(accessToken, editSessionId).catch(() => undefined);
      }
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
    }, EXECUTION_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [accessToken, drafts, editSessionId]);

  const selected = useMemo(
    () => versions.find((version) => version.id === selectedId) ?? null,
    [selectedId, versions],
  );

  useEffect(() => {
    // Collapsed, so the list reads as an index of what this version holds. It
    // opened the first 来源 by default, which put a few thousand characters of
    // body between the reader and everything below it — including the 主题.
    if (!editSessionId) setOpenSourceKey(null);
  }, [editSessionId, selected]);

  async function beginEditing() {
    setBusy(true);
    try {
      const edit = await createSourceEditSession(accessToken, taskId);
      setEditSessionId(edit.id);
      setSaveIdempotencyKey(crypto.randomUUID());
      const nextDrafts = edit.base_version.sources.map(draftOf);
      setDrafts(nextDrafts);
      setThemeDraft(edit.base_version.theme ?? "");
      // Collapsed, as the read-only list is. Editing opens with the version's
      // shape in view — its 来源 and its 主题 — rather than with a few thousand
      // characters of the first 来源 pushing everything else off the screen.
      setOpenSourceKey(null);
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
      setOpenSourceKey(replaceKey ?? staged.key);
      setNewTitle("");
      setNewBody("");
      setNewProvenance("");
      setNewUrl("");
      setNewFile(null);
      setReplaceKey(null);
      setAdding(false);
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
    // From here until this either lands or fails, leaving the pane must not
    // discard the session out from under the request.
    savingRef.current = true;
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
        theme: (themeDraft ?? "").trim() || null,
      });
      const history = await listTaskVersions(accessToken, taskId);
      setVersions(history.items);
      setSelectedId(saved.id);
      setEditSessionId(null);
      setSaveIdempotencyKey(null);
      setDrafts([]);
      setThemeDraft(null);
      announceSelection(saved.id);
      currentChangeRef.current(saved);
      setError(null);
    } catch {
      // Refused or unreachable: the session is still the writer's to abandon,
      // so leaving may discard it again.
      savingRef.current = false;
      setError(SAVE_FAILED);
    } finally {
      setBusy(false);
    }
  }

  // A staged input must have finished preparing; its warnings are shown on the
  // source rather than gated behind an acknowledgement, as in task creation.
  const stagedReady = drafts.every((source) =>
    !source.prepared || ["ready", "warning"].includes(source.prepared.status),
  );
  // A 主题 edit is a change like any other — and the only kind a user can make
  // without touching a 来源, so without this the save button stayed dead.
  const themeChanged =
    themeDraft !== null && (themeDraft ?? "").trim() !== (selected?.theme ?? "");
  const hasChanges = selected !== null && (
    themeChanged
    || drafts.length !== selected.sources.length
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
    setBusy(true);
    try {
      await discardSourceEditSession(accessToken, editSessionId);
      setEditSessionId(null);
      setSaveIdempotencyKey(null);
      setDrafts([]);
      setThemeDraft(null);
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
    setDrafts((current) => {
      const remaining = current.filter((item) => item.key !== source.key);
      if (openSourceKey === source.key) setOpenSourceKey(null);
      return remaining;
    });
  }

  async function restore() {
    if (!selected) return;
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
      announceSelection(restored.id);
      currentChangeRef.current(restored);
      setError(null);
    } catch {
      setError(RESTORE_FAILED);
    } finally {
      setBusy(false);
    }
  }

  /*
   * The fields a staged input needs, shared by adding a source and replacing
   * one. A plain function rather than a nested component: a component declared
   * here would be a new type on every render, remounting these inputs and
   * dropping focus on every keystroke.
   */
  function stagingFields() {
    return (
      <>
        <div className="source-kind-tabs" aria-label={t("来源类型")}>
          <button type="button" className={`button ${newMode === "pasted" ? "" : "button--quiet"}`} onClick={() => setNewMode("pasted")}>{t("粘贴文本")}</button>
          <button type="button" className={`button ${newMode === "url" ? "" : "button--quiet"}`} onClick={() => setNewMode("url")}>{t("公共文章链接")}</button>
          <button type="button" className={`button ${newMode === "file" ? "" : "button--quiet"}`} onClick={() => setNewMode("file")}>{t("上传文件")}</button>
        </div>
        {newMode === "pasted" ? (
          <>
            <label>{t("新来源标题")}<input required value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /></label>
            <label>{t("新来源正文")}<textarea required value={newBody} onChange={(event) => setNewBody(event.target.value)} /></label>
            <label>{t("新来源信息")}<input value={newProvenance} onChange={(event) => setNewProvenance(event.target.value)} /></label>
          </>
        ) : newMode === "url" ? (
          <label>{t("新来源网址")}<input type="url" required value={newUrl} onChange={(event) => setNewUrl(event.target.value)} /></label>
        ) : (
          <>
            <label>{t("新来源文件")}<input type="file" required accept=".pdf,.docx,.txt,.md" onChange={(event) => setNewFile(event.target.files?.[0] ?? null)} /></label>
            <p className="form-hint">{t("支持 PDF、DOCX、TXT 和 Markdown；扫描件不支持 OCR。")}</p>
          </>
        )}
      </>
    );
  }

  if (!selected) {
    return <p role={error ? "alert" : undefined}>{error ?? t("版本加载中")}</p>;
  }

  return (
    <section className="source-versions" aria-labelledby={`sources-${taskId}`}>
      {/*
       * One row where there were three. 来源 was printed twice and the version
       * three times — as a heading, as a count suffix, and inside the control
       * that sets it — while the two actions sat at the far bottom of the page.
       * What is left is the version being shown and what can be done to it.
       */}
      <h3 className="sr-only" id={`sources-${taskId}`}>
        {selected.is_current
          ? locale === "en" ? `Current version V${selected.number}` : `当前版本 V${selected.number}`
          : locale === "en" ? `Read-only history V${selected.number}` : `只读历史 V${selected.number}`}
      </h3>
      <div className="source-toolbar">
        <label className="source-toolbar__version">
          <span className="sr-only">{t("版本")}</span>
          <select
            value={selected.id}
            disabled={editSessionId !== null}
            onChange={(event) => {
              setSelectedId(event.target.value);
              announceSelection(event.target.value);
            }}
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {t("版本")} V{version.number}{version.is_current ? t("（当前）") : t("（历史）")}
              </option>
            ))}
          </select>
        </label>
        {!selected.is_current ? <span className="source-chip">{t("只读")}</span> : null}
        <div className="source-toolbar__actions">
          {!editSessionId && selected.capabilities.can_edit ? (
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => void beginEditing()}>
              {t("编辑")}
            </button>
          ) : null}
          {!editSessionId && selected.capabilities.can_restore ? (
            <button className="button" type="button" disabled={busy} onClick={() => setConfirming("restore")}>
              {t("恢复为当前版本")}
            </button>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="form-error">
          {domainMessage(error)}
          {isCreditRefusal(error) ? <BuyCreditsLink /> : null}
        </p>
      ) : null}
      {editSessionId ? (
        <>
          <p className="form-hint">
            {locale === "en" ? `The current version remains V${selected.number}; changes enter history only when saved.` : `当前版本仍是 V${selected.number}；保存前的改动不会进入历史。`}
          </p>
          <p className="section-kicker">{t("添加 1-3 个来源")}</p>

          {/* The same list, items, and add-a-source flow as task creation: a
              writer edits sources in one place whether the task exists yet or
              not. What differs is only when it commits — here, on 保存来源修改. */}
          <ol className="source-list">
            {drafts.map((source, position) => (
              <li key={source.key}>
                <article
                  className={`source-operation${source.prepared ? ` source-operation--${source.prepared.status}` : ""}`}
                >
                  <button
                    className="source-operation__summary"
                    type="button"
                    aria-expanded={openSourceKey === source.key}
                    aria-controls={`source-editor-${source.key}`}
                    aria-label={`${t("编辑来源")} ${source.title || t("未命名来源")}`}
                    onClick={() => setOpenSourceKey((current) => current === source.key ? null : source.key)}
                  >
                    <span className="source-operation__status">
                      <strong>
                        <span className="source-operation__index">{position + 1}</span>
                        {openSourceKey === source.key
                          ? <ChevronDown size={15} aria-hidden="true" />
                          : <ChevronRight size={15} aria-hidden="true" />}
                        {source.title || t("未命名来源")}
                      </strong>
                      {source.prepared ? (
                        <span className={`source-chip source-chip--${source.prepared.status}`}>
                          {t(PREPARED_STATUS_LABELS[source.prepared.status])}
                        </span>
                      ) : null}
                    </span>
                  </button>

                  {source.prepared?.status === "processing" ? (
                    <RunningNotice label={t("正在处理来源…")} />
                  ) : null}
                  {source.prepared?.warnings.map((warning) => (
                    <p className="source-note source-note--warning" key={warning.code}>
                      {domainMessage(warning.message, warning.code)}
                    </p>
                  ))}

                  {replaceKey === source.key ? (
                    <form className="source-operation__editor source-fields" onSubmit={(event) => void stageInput(event)}>
                      {stagingFields()}
                      <div className="button-row">
                        <button className="button" type="submit" disabled={busy}>{t("确认替换")}</button>
                        <button className="button button--quiet" type="button" onClick={() => setReplaceKey(null)}>
                          {t("取消替换")}
                        </button>
                      </div>
                    </form>
                  ) : openSourceKey === source.key ? (
                    <fieldset className="source-operation__editor source-fields" id={`source-editor-${source.key}`} aria-label={`${t("来源")} ${source.title}`}>
                      <label>
                        {t("来源标题")}
                        <input
                          value={source.title}
                          onChange={(event) => updateDraft(source.key, { title: event.target.value })}
                        />
                      </label>
                      <label>
                        {t("来源正文")}
                        <textarea
                          value={source.body}
                          onChange={(event) => updateDraft(source.key, { body: event.target.value })}
                        />
                      </label>
                      <label>
                        {t("来源信息")}
                        <input
                          value={source.provenance}
                          onChange={(event) => updateDraft(source.key, { provenance: event.target.value })}
                        />
                      </label>
                      <div className="button-row">
                        {/* Kept, unlike in creation: replacing preserves the source's
                            identity across task versions, which delete-then-add loses. */}
                        <button
                          className="button button--quiet"
                          type="button"
                          aria-label={`${t("替换来源")} ${source.title}`}
                          onClick={() => {
                            setAdding(false);
                            setReplaceKey(source.key);
                          }}
                        >
                          {t("替换来源")}
                        </button>
                        <button
                          className="button button--quiet button--quiet-danger"
                          type="button"
                          disabled={drafts.length === 1}
                          aria-label={`${t("删除来源")} ${source.title}`}
                          onClick={() => void removeDraft(source)}
                        >
                          {t("删除来源")}
                        </button>
                      </div>
                    </fieldset>
                  ) : null}
                </article>
              </li>
            ))}

            {adding ? (
              <li>
                <article className="source-operation source-operation--draft">
                  <p className="source-operation__summary source-operation__summary--draft">
                    <strong>
                      <span className="source-operation__index">{drafts.length + 1}</span>
                      {t("新来源")}
                    </strong>
                    <span className="source-operation__pending">{t("尚未添加")}</span>
                  </p>
                  <form className="source-operation__editor source-fields" onSubmit={(event) => void stageInput(event)}>
                    {stagingFields()}
                    <div className="button-row">
                      <button className="button" type="submit" disabled={busy}>{t("添加来源")}</button>
                      <button className="button button--quiet" type="button" disabled={busy} onClick={() => setAdding(false)}>
                        {t("取消")}
                      </button>
                    </div>
                  </form>
                </article>
              </li>
            ) : null}
          </ol>

          {drafts.length < 3 ? (
            !adding && !replaceKey ? (
              <button
                className="add-source-button"
                type="button"
                onClick={() => {
                  setOpenSourceKey(null);
                  setAdding(true);
                }}
              >
                <Plus size={18} aria-hidden="true" /> {t("添加来源")}
              </button>
            ) : null
          ) : <p className="creation-hint">{t("已达到三个来源上限；删除一个来源后可继续添加。")}</p>}

          {editSessionId ? (
            <ThemeChoice
              accessToken={accessToken}
              clientSessionId={editSessionId}
              theme={themeDraft ?? ""}
              onThemeChange={setThemeDraft}
              // Every draft as it stands, including text typed and not yet
              // saved: that is what the writer is looking at, and a candidate
              // drawn from the 来源 they have replaced would be about material
              // that is on its way out.
              sources={drafts.map((source) => ({
                title: source.title,
                body: source.body,
                provenance: source.provenance || null,
              }))}
              canPropose={stagedReady && !busy && drafts.length > 0}
              disabledReason={stagedReady ? null : "请等待所有来源处理完成。"}
              footnote={t("最多 80 字。清空即移除主题及其知言报告；改写主题会重新生成报告。")}
              inputId="edit-theme"
            />
          ) : null}

          <div className="workspace__actions">
            <button className="button" type="button" disabled={busy || !stagedReady || !hasChanges} onClick={() => void save()}>
              {t("保存修改")}
            </button>
            <button className="button button--quiet" type="button" disabled={busy} onClick={() => setConfirming("discard")}>
              {t("放弃编辑")}
            </button>
          </div>
        </>
      ) : (
        <>
          <ol className="source-list">
            {selected.sources.map((source, position) => (
              <li key={source.id}>
                <article className="source-operation">
                  <button
                    className="source-operation__summary"
                    type="button"
                    aria-expanded={openSourceKey === source.source_id}
                    aria-controls={`source-body-${source.id}`}
                    onClick={() => setOpenSourceKey((current) =>
                      current === source.source_id ? null : source.source_id)}
                  >
                    {/* The same summary row a 来源 has while it is being added:
                        the number, the disclosure chevron, the title, and one
                        muted word on the right. */}
                    <span className="source-operation__status">
                      <strong>
                        <span className="source-operation__index">{position + 1}</span>
                        {openSourceKey === source.source_id
                          ? <ChevronDown size={15} aria-hidden="true" />
                          : <ChevronRight size={15} aria-hidden="true" />}
                        {source.title}
                      </strong>
                      <span className="source-operation__pending">
                        {openSourceKey === source.source_id ? t("收起") : t("展开")}
                      </span>
                    </span>
                  </button>
                  {openSourceKey === source.source_id ? (
                    <div className="source-version-body" id={`source-body-${source.id}`}>
                      <p>{source.provenance ?? t("未提供来源信息")}</p>
                      <pre>{source.body}</pre>
                    </div>
                  ) : null}
                </article>
              </li>
            ))}
          </ol>
          {/*
            The 主题 under the 来源 it was drawn from, which is the order they
            were decided in and the order they are read in. It was a chip in the
            toolbar beside the version picker, where a sentence of up to eighty
            characters had to be truncated to fit and sat among controls rather
            than among material.
          */}
          {/*
            The 主题 as the same card the 来源 above it are, and after them: it
            is what they turned out to be about, and it is read last.
          */}
          <article className="source-operation source-operation--theme">
            <p className="source-operation__status source-operation__summary--theme">
              <strong>{t("主题")}</strong>
              {selected.theme ? null : (
                <span className="source-operation__pending">{t("未设置")}</span>
              )}
            </p>
            {selected.theme ? (
              <p className="version-theme__text">{selected.theme}</p>
            ) : (
              <p className="version-theme__absent">
                {t("这一版没有主题；编辑时可以添加，知言将围绕它检索来源之外的信息。")}
              </p>
            )}
          </article>
          {selected.capabilities.unavailable_reason ? (
            <p className="form-hint">{domainMessage(selected.capabilities.unavailable_reason)}</p>
          ) : null}
        </>
      )}
      <ConfirmDialog
        open={confirming === "discard"}
        title={t("放弃这次来源编辑？")}
        body={t("未保存的来源修改会被丢弃，且无法恢复。")}
        confirmLabel={t("放弃编辑")}
        danger
        onOpenChange={(open) => setConfirming(open ? "discard" : null)}
        onConfirm={() => void discard()}
      />
      <ConfirmDialog
        open={confirming === "restore"}
        title={locale === "en"
          ? `Restore V${selected.number} as the current version?`
          : `确定将 V${selected.number} 恢复为当前版本吗？`}
        confirmLabel={t("恢复为当前版本")}
        onOpenChange={(open) => setConfirming(open ? "restore" : null)}
        onConfirm={() => void restore()}
      />
    </section>
  );
}

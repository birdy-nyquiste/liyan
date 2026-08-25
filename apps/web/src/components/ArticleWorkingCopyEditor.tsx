import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef } from "react";

import { articleExtensions } from "./articleEditorSchema";
import {
  canonicalMarkdownToTiptap,
  isSafeArticleHref,
  tiptapToCanonicalMarkdown,
} from "./articleMarkdown";
import type { LiyanWorkingCopy } from "./workingCopyStorage";
import { useInterfaceLocale } from "../interfaceLocale";

export function ArticleWorkingCopyEditor({
  taskId,
  value,
  disabled,
  onChange,
}: {
  taskId: string;
  value: LiyanWorkingCopy;
  disabled: boolean;
  onChange(value: LiyanWorkingCopy): void;
}) {
  const { locale, t } = useInterfaceLocale();
  const valueRef = useRef(value);
  const localValues = useRef(new WeakSet<object>());
  valueRef.current = value;
  const changeLocally = (next: LiyanWorkingCopy) => {
    localValues.current.add(next);
    onChange(next);
  };
  const editor = useEditor({
    extensions: articleExtensions,
    content: canonicalMarkdownToTiptap(value.body_markdown),
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        "aria-label": t("文章正文"),
        class: "liyan-editor__content",
        role: "textbox",
      },
    },
    onUpdate: ({ editor: current }) => {
      const bodyMarkdown = tiptapToCanonicalMarkdown(current.getJSON());
      changeLocally({
        ...valueRef.current,
        body_markdown: bodyMarkdown,
      });
    },
  }, [locale, taskId]);

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!disabled);
  }, [disabled, editor]);

  useEffect(() => {
    if (!editor) return;
    if (localValues.current.has(value)) return;
    const current = tiptapToCanonicalMarkdown(editor.getJSON());
    if (current !== value.body_markdown) {
      editor.commands.setContent(canonicalMarkdownToTiptap(value.body_markdown), {
        emitUpdate: false,
      });
    }
  }, [editor, value]);

  const action = (label: string, run: () => void, active = false) => (
    <button
      className="button button--quiet liyan-toolbar__button"
      type="button"
      aria-label={label}
      aria-pressed={active}
      disabled={disabled || !editor}
      onClick={run}
    >
      {label}
    </button>
  );

  const editLink = () => {
    if (!editor) return;
    const current = String(editor.getAttributes("link").href ?? "");
    const href = window.prompt(locale === "en" ? "Enter an http or https URL" : "请输入 http 或 https 链接", current);
    if (href === null) return;
    if (!href) editor.chain().focus().extendMarkRange("link").unsetLink().run();
    else if (isSafeArticleHref(href)) {
      editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
    }
  };

  return (
    <article className="liyan-working-copy" aria-label={t("未保存 Working Copy")}>
      <p className="section-kicker">{t("未保存 Working Copy")}</p>
      <label htmlFor={`liyan-title-${taskId}`}>{t("文章标题")}</label>
      <input
        id={`liyan-title-${taskId}`}
        value={value.title}
        disabled={disabled}
        onChange={(event) => changeLocally({ ...value, title: event.target.value })}
      />
      <div className="liyan-toolbar" role="toolbar" aria-label={t("文章格式")}>
        {action(t("正文"), () => editor?.chain().focus().setParagraph().run())}
        {action(t("二级标题"), () => editor?.chain().focus().toggleHeading({ level: 2 }).run())}
        {action(t("三级标题"), () => editor?.chain().focus().toggleHeading({ level: 3 }).run())}
        {action(t("加粗"), () => editor?.chain().focus().toggleBold().run(), editor?.isActive("bold"))}
        {action(t("斜体"), () => editor?.chain().focus().toggleItalic().run(), editor?.isActive("italic"))}
        {action(t("无序列表"), () => editor?.chain().focus().toggleBulletList().run())}
        {action(t("有序列表"), () => editor?.chain().focus().toggleOrderedList().run())}
        {action(t("引用"), () => editor?.chain().focus().toggleBlockquote().run())}
        {action(t("链接"), editLink, editor?.isActive("link"))}
        {action(t("分隔线"), () => editor?.chain().focus().setHorizontalRule().run())}
      </div>
      <EditorContent editor={editor} />
      <p className="form-hint">
        {t("仅保存在当前浏览器；退出登录、换设备或清除浏览器数据后无法恢复。")}
      </p>
    </article>
  );
}

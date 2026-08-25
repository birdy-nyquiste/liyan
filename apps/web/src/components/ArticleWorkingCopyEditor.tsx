import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Bold,
  Heading2,
  Heading3,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Pilcrow,
  Quote,
} from "lucide-react";

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
  toolbarSlot,
}: {
  taskId: string;
  value: LiyanWorkingCopy;
  disabled: boolean;
  onChange(value: LiyanWorkingCopy): void;
  /** Where the formatting controls are rendered, when the pane offers a place. */
  toolbarSlot?: HTMLElement | null;
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

  // Icons, because the toolbar now shares one row with the article's actions and
  // ten words do not fit beside them. The name each button had is what a screen
  // reader still hears and what a pointer still sees on hover.
  const action = (label: string, icon: ReactNode, run: () => void, active = false) => (
    <button
      className="button button--quiet liyan-toolbar__button"
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      disabled={disabled || !editor}
      onClick={run}
    >
      {icon}
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

  const toolbarControls = (
    <div className="liyan-toolbar" role="toolbar" aria-label={t("文章格式")}>
      {action(t("正文"), <Pilcrow size={15} aria-hidden="true" />, () => editor?.chain().focus().setParagraph().run())}
      {action(t("二级标题"), <Heading2 size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleHeading({ level: 2 }).run())}
      {action(t("三级标题"), <Heading3 size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleHeading({ level: 3 }).run())}
      {action(t("加粗"), <Bold size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleBold().run(), editor?.isActive("bold"))}
      {action(t("斜体"), <Italic size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleItalic().run(), editor?.isActive("italic"))}
      {action(t("无序列表"), <List size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleBulletList().run())}
      {action(t("有序列表"), <ListOrdered size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleOrderedList().run())}
      {action(t("引用"), <Quote size={15} aria-hidden="true" />, () => editor?.chain().focus().toggleBlockquote().run())}
      {action(t("链接"), <Link2 size={15} aria-hidden="true" />, editLink, editor?.isActive("link"))}
      {action(t("分隔线"), <Minus size={15} aria-hidden="true" />, () => editor?.chain().focus().setHorizontalRule().run())}
    </div>
  );
  // Formatting belongs with the article's other actions rather than in a band of
  // its own above the text; the editor still owns it, it is only rendered there.
  const toolbar = toolbarSlot ? createPortal(toolbarControls, toolbarSlot) : toolbarControls;

  return (
    <article className="liyan-working-copy" aria-label={t("未保存的草稿")}>
      {/* A document's title is its title, not a labelled field in a form. The
          label stays for anyone who cannot see where the caret is. */}
      <label className="sr-only" htmlFor={`liyan-title-${taskId}`}>{t("文章标题")}</label>
      <input
        className="liyan-working-copy__title"
        placeholder={t("文章标题")}
        id={`liyan-title-${taskId}`}
        value={value.title}
        disabled={disabled}
        onChange={(event) => changeLocally({ ...value, title: event.target.value })}
      />
      {toolbar}
      <EditorContent editor={editor} />
    </article>
  );
}

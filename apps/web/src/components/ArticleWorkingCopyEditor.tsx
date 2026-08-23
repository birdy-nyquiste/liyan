import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useRef } from "react";

import {
  canonicalMarkdownToTiptap,
  tiptapToCanonicalMarkdown,
} from "./articleMarkdown";
import type { LiyanWorkingCopy } from "./workingCopyStorage";

const extensions = [StarterKit.configure({
  code: false,
  codeBlock: false,
  strike: false,
  hardBreak: false,
  heading: { levels: [2, 3] },
  link: {
    autolink: false,
    linkOnPaste: true,
    openOnClick: false,
    protocols: ["http", "https"],
    HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
  },
})];

const safeHref = (href: string): boolean => {
  try {
    const protocol = new URL(href).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
};

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
  const valueRef = useRef(value);
  const localValues = useRef(new WeakSet<object>());
  valueRef.current = value;
  const changeLocally = (next: LiyanWorkingCopy) => {
    localValues.current.add(next);
    onChange(next);
  };
  const editor = useEditor({
    extensions,
    content: canonicalMarkdownToTiptap(value.body_markdown),
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        "aria-label": "文章正文",
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
  }, [taskId]);

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
    const href = window.prompt("请输入 http 或 https 链接", current);
    if (href === null) return;
    if (!href) editor.chain().focus().extendMarkRange("link").unsetLink().run();
    else if (safeHref(href)) editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
  };

  return (
    <article className="liyan-working-copy" aria-label="未保存 Working Copy">
      <p className="section-kicker">未保存 Working Copy</p>
      <label htmlFor={`liyan-title-${taskId}`}>文章标题</label>
      <input
        id={`liyan-title-${taskId}`}
        value={value.title}
        disabled={disabled}
        onChange={(event) => changeLocally({ ...value, title: event.target.value })}
      />
      <div className="liyan-toolbar" role="toolbar" aria-label="文章格式">
        {action("正文", () => editor?.chain().focus().setParagraph().run())}
        {action("二级标题", () => editor?.chain().focus().toggleHeading({ level: 2 }).run())}
        {action("三级标题", () => editor?.chain().focus().toggleHeading({ level: 3 }).run())}
        {action("加粗", () => editor?.chain().focus().toggleBold().run(), editor?.isActive("bold"))}
        {action("斜体", () => editor?.chain().focus().toggleItalic().run(), editor?.isActive("italic"))}
        {action("无序列表", () => editor?.chain().focus().toggleBulletList().run())}
        {action("有序列表", () => editor?.chain().focus().toggleOrderedList().run())}
        {action("引用", () => editor?.chain().focus().toggleBlockquote().run())}
        {action("链接", editLink, editor?.isActive("link"))}
        {action("分隔线", () => editor?.chain().focus().setHorizontalRule().run())}
      </div>
      <EditorContent editor={editor} />
      <p className="form-hint">
        仅保存在当前浏览器；退出登录、换设备或清除浏览器数据后无法恢复。
      </p>
    </article>
  );
}

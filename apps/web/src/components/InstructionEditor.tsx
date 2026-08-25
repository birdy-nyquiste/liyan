import { mergeAttributes, Node, type JSONContent } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useRef } from "react";
import { useInterfaceLocale } from "../interfaceLocale";

import type { InstructionCapsule, InstructionDocument } from "../api/client";

export type CapsuleSelection = {
  nonce: number;
  label: string;
  reference: InstructionCapsule;
};

export type CapsuleChoice = Omit<CapsuleSelection, "nonce">;

const InstructionCapsuleNode = Node.create({
  name: "instructionCapsule",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      taskVersionId: { default: "" },
      reportId: { default: "" },
      itemId: { default: "" },
      label: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-instruction-capsule]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-instruction-capsule": "",
        class: "liyan-capsule",
        contenteditable: "false",
      }),
      String(HTMLAttributes.label || HTMLAttributes.itemId),
    ];
  },

  addKeyboardShortcuts() {
    const deleteCapsule = (direction: -1 | 1) => {
      const { selection } = this.editor.state;
      const { empty, $from } = selection;
      if (!empty && $from.nodeAfter?.type.name === this.name) {
        return this.editor.commands.deleteSelection();
      }
      const adjacent = direction < 0 ? $from.nodeBefore : $from.nodeAfter;
      if (!empty || adjacent?.type.name !== this.name) return false;
      return this.editor.commands.command(({ dispatch, tr }) => {
        const start = direction < 0 ? $from.pos - 1 : $from.pos;
        dispatch?.(tr.delete(start, start + 1));
        return true;
      });
    };
    return {
      Backspace: () => deleteCapsule(-1),
      Delete: () => deleteCapsule(1),
    };
  },
});

const extensions = [
  StarterKit.configure({
    blockquote: false,
    bold: false,
    bulletList: false,
    code: false,
    codeBlock: false,
    dropcursor: false,
    gapcursor: false,
    hardBreak: false,
    heading: false,
    horizontalRule: false,
    italic: false,
    link: false,
    listItem: false,
    listKeymap: false,
    orderedList: false,
    strike: false,
    underline: false,
  }),
  InstructionCapsuleNode,
];

export function InstructionEditor({
  taskId,
  value,
  disabled = false,
  selection,
  onChange,
}: {
  taskId: string;
  value: InstructionDocument;
  disabled?: boolean;
  selection?: CapsuleSelection | null;
  onChange(value: InstructionDocument): void;
}) {
  const { locale, t } = useInterfaceLocale();
  const localValues = useRef(new WeakSet<object>());
  const editor = useEditor({
    extensions,
    content: toTiptap(value),
    editable: !disabled,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        "aria-label": t("立言指令（可选）"),
        class: "liyan-instruction-editor__content",
        role: "textbox",
      },
    },
    onUpdate: ({ editor: current }) => {
      const next = fromTiptap(current.getJSON());
      localValues.current.add(next);
      onChange(next);
    },
  }, [locale, taskId]);

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [disabled, editor]);

  useEffect(() => {
    if (!editor) return;
    if (localValues.current.has(value)) return;
    const current = fromTiptap(editor.getJSON());
    if (JSON.stringify(current) !== JSON.stringify(normalize(value))) {
      editor.commands.setContent(toTiptap(value), { emitUpdate: false });
    }
  }, [editor, value]);

  useEffect(() => {
    if (!editor || !selection) return;
    let existingPosition: number | null = null;
    editor.state.doc.descendants((node, position) => {
      if (
        node.type.name === "instructionCapsule"
        && node.attrs.taskVersionId === selection.reference.task_version_id
        && node.attrs.reportId === selection.reference.report_id
        && node.attrs.itemId === selection.reference.item_id
      ) {
        existingPosition = position;
        return false;
      }
      return true;
    });
    if (existingPosition !== null) {
      editor.chain().focus().setNodeSelection(existingPosition).scrollIntoView().run();
      return;
    }
    const insertionPosition = editor.state.selection.from;
    editor.chain().focus().insertContent({
      type: "instructionCapsule",
      attrs: {
        taskVersionId: selection.reference.task_version_id,
        reportId: selection.reference.report_id,
        itemId: selection.reference.item_id,
        label: selection.label,
      },
    }).setTextSelection(insertionPosition + 1).run();
  }, [editor, selection]);

  return (
    <div className="liyan-instruction-editor">
      <EditorContent editor={editor} />
      <p className="form-hint">{t("可从知言报告中引用内容")}</p>
    </div>
  );
}

function normalize(value: InstructionDocument): Required<InstructionDocument> {
  return { content: value.content ?? [] };
}

function toTiptap(value: InstructionDocument): JSONContent {
  const paragraphs: JSONContent[] = [{ type: "paragraph", content: [] }];
  for (const part of value.content ?? []) {
    if (part.type === "capsule") {
      paragraphs.at(-1)!.content!.push({
        type: "instructionCapsule",
        attrs: {
          taskVersionId: part.task_version_id,
          reportId: part.report_id,
          itemId: part.item_id,
          label: part.item_id,
        },
      });
      continue;
    }
    const lines = part.text.split("\n");
    lines.forEach((line, index) => {
      if (index > 0) paragraphs.push({ type: "paragraph", content: [] });
      if (line) paragraphs.at(-1)!.content!.push({ type: "text", text: line });
    });
  }
  return { type: "doc", content: paragraphs };
}

function fromTiptap(document: JSONContent): Required<InstructionDocument> {
  const content: NonNullable<InstructionDocument["content"]> = [];
  const pushText = (text: string) => {
    if (!text) return;
    const previous = content.at(-1);
    if (previous?.type === "text") previous.text += text;
    else content.push({ type: "text", text });
  };
  (document.content ?? []).forEach((paragraph, paragraphIndex) => {
    if (paragraphIndex > 0) pushText("\n");
    for (const node of paragraph.content ?? []) {
      if (node.type === "text") pushText(node.text ?? "");
      else if (node.type === "instructionCapsule") {
        content.push({
          type: "capsule",
          task_version_id: String(node.attrs?.taskVersionId ?? ""),
          report_id: String(node.attrs?.reportId ?? ""),
          item_id: String(node.attrs?.itemId ?? ""),
        });
      }
    }
  });
  return { content };
}

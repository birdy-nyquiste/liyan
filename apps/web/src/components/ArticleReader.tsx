import { EditorContent, useEditor } from "@tiptap/react";

import { articleExtensions } from "./articleEditorSchema";
import { canonicalMarkdownToTiptap } from "./articleMarkdown";

/**
 * A saved article rendered through the same constrained schema that edits it.
 *
 * Historical Revisions are explicit and read-only, and the Markdown is never
 * turned into HTML on its own: it goes through the allowed Tiptap document.
 */
export function ArticleReader({ label, bodyMarkdown }: { label: string; bodyMarkdown: string }) {
  const editor = useEditor({
    extensions: articleExtensions,
    content: canonicalMarkdownToTiptap(bodyMarkdown),
    editable: false,
    immediatelyRender: false,
    editorProps: {
      attributes: { "aria-label": label, class: "liyan-editor__content", role: "document" },
    },
  }, [bodyMarkdown]);

  return <EditorContent editor={editor} />;
}

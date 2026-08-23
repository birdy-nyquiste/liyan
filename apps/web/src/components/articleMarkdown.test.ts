import { describe, expect, it } from "vitest";

import {
  canonicalMarkdownToTiptap,
  tiptapToCanonicalMarkdown,
} from "./articleMarkdown";

describe("canonical article Markdown", () => {
  it("round-trips every allowed article construct deterministically", () => {
    const markdown = [
      "第一段包含 **加粗**、*斜体* 和 [安全链接](https://example.com/path)。",
      "",
      "## 二级标题",
      "",
      "### 三级标题",
      "",
      "- 无序一",
      "- 无序二",
      "",
      "1. 有序一",
      "2. 有序二",
      "",
      "> 一段引用。",
      "",
      "---",
      "",
      "最后一段。",
    ].join("\n");

    expect(tiptapToCanonicalMarkdown(canonicalMarkdownToTiptap(markdown))).toBe(markdown);
  });

  it("serializes an independently authored Tiptap document to canonical Markdown", () => {
    expect(tiptapToCanonicalMarkdown({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "可信", marks: [{ type: "bold" }] },
            { type: "text", text: "链接", marks: [{ type: "link", attrs: { href: "http://example.com" } }] },
          ],
        },
        { type: "horizontalRule" },
      ],
    })).toBe("**可信**[链接](http://example.com)\n\n---");
  });

  it("strips unsupported and unsafe pasted constructs while retaining readable text", () => {
    const pasted = [
      "# 不允许的一级标题",
      "",
      "<script>危险内容</script><p>保留正文</p>",
      "",
      "| 甲 | 乙 |",
      "| --- | --- |",
      "| 一 | 二 |",
      "",
      "![配图](https://example.com/a.png)",
      "",
      "[危险链接](javascript:alert(1)) 与 [相对链接](/internal)。",
      "",
      "`行内代码` 与 ~~删除线~~。",
    ].join("\n");

    expect(tiptapToCanonicalMarkdown(canonicalMarkdownToTiptap(pasted))).toBe([
      "不允许的一级标题",
      "",
      "保留正文",
      "",
      "甲 / 乙",
      "",
      "一 / 二",
      "",
      "配图",
      "",
      "危险链接 与 相对链接。",
      "",
      "行内代码 与 删除线。",
    ].join("\n"));
  });

  it("normalizes malformed Markdown to an idempotent safe document", () => {
    const malformed = "**未闭合\n\n[危险链接](javascript:alert(1\n\n<broken-tag";
    const normalized = tiptapToCanonicalMarkdown(canonicalMarkdownToTiptap(malformed));

    expect(normalized).not.toMatch(/javascript:|<broken-tag/);
    expect(tiptapToCanonicalMarkdown(canonicalMarkdownToTiptap(normalized))).toBe(normalized);
  });
});

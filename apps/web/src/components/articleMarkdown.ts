import type { JSONContent } from "@tiptap/core";
import { marked, type Token, type Tokens } from "marked";

type TiptapMark = NonNullable<JSONContent["marks"]>[number];

export const isSafeArticleHref = (href: string): boolean => {
  try {
    const parsed = new URL(href);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
};

const plainHtmlText = (html: string): string => html
  .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, "")
  .replace(/<!--[\s\S]*?-->/g, "")
  .replace(/<[^>]*>/g, "")
  .trim();

const textNode = (text: string, marks: TiptapMark[] = []): JSONContent[] =>
  text ? [{ type: "text", text, ...(marks.length ? { marks } : {}) }] : [];

function inlineContent(tokens: Token[], marks: TiptapMark[] = []): JSONContent[] {
  return tokens.flatMap((token): JSONContent[] => {
    switch (token.type) {
      case "text":
        return token.tokens?.length
          ? inlineContent(token.tokens, marks)
          : textNode(token.text, marks);
      case "escape":
      case "codespan":
        return textNode(token.text, marks);
      case "strong":
        return inlineContent(token.tokens ?? [], [...marks, { type: "bold" }]);
      case "em":
        return inlineContent(token.tokens ?? [], [...marks, { type: "italic" }]);
      case "del":
        return inlineContent(token.tokens ?? [], marks);
      case "link":
        return inlineContent(
          token.tokens ?? [],
          isSafeArticleHref(token.href)
            ? [...marks, { type: "link", attrs: { href: token.href } }]
            : marks,
        );
      case "image":
        return textNode(token.text, marks);
      case "br":
        return textNode(" ", marks);
      case "html":
        return textNode(plainHtmlText(token.text), marks);
      default:
        return "text" in token && typeof token.text === "string"
          ? textNode(token.text, marks)
          : [];
    }
  });
}

const paragraph = (tokens: Token[]): JSONContent | null => {
  const content = inlineContent(tokens);
  return content.length ? { type: "paragraph", content } : null;
};

function listItem(item: Tokens.ListItem): JSONContent {
  const content = blockContent(item.tokens);
  return {
    type: "listItem",
    content: content.length ? content : [{ type: "paragraph" }],
  };
}

function tableRows(table: Tokens.Table): JSONContent[] {
  return [table.header, ...table.rows].flatMap((row) => {
    const content = row.flatMap((cell, index) => [
      ...(index ? textNode(" / ") : []),
      ...inlineContent(cell.tokens),
    ]);
    return content.length ? [{ type: "paragraph", content }] : [];
  });
}

function blockContent(tokens: Token[]): JSONContent[] {
  return tokens.flatMap((token): JSONContent[] => {
    switch (token.type) {
      case "space":
      case "def":
        return [];
      case "paragraph": {
        const node = paragraph(token.tokens ?? []);
        return node ? [node] : [];
      }
      case "text": {
        const node = paragraph(token.tokens?.length ? token.tokens : [token]);
        return node ? [node] : [];
      }
      case "heading": {
        const content = inlineContent(token.tokens ?? []);
        if (!content.length) return [];
        return token.depth === 2 || token.depth === 3
          ? [{ type: "heading", attrs: { level: token.depth }, content }]
          : [{ type: "paragraph", content }];
      }
      case "hr":
        return [{ type: "horizontalRule" }];
      case "blockquote": {
        const content = blockContent(token.tokens ?? []);
        return content.length ? [{ type: "blockquote", content }] : [];
      }
      case "list":
        return [{
          type: token.ordered ? "orderedList" : "bulletList",
          ...(token.ordered && token.start !== "" && token.start !== 1
            ? { attrs: { start: token.start } }
            : {}),
          content: token.items.map(listItem),
        }];
      case "table":
        return tableRows(token as Tokens.Table);
      case "code":
        return token.text ? [{ type: "paragraph", content: textNode(token.text) }] : [];
      case "html": {
        const text = plainHtmlText(token.text);
        return text ? [{ type: "paragraph", content: textNode(text) }] : [];
      }
      default:
        return [];
    }
  });
}

export function canonicalMarkdownToTiptap(markdown: string): JSONContent {
  const sanitized = markdown
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, "")
    .replace(/\[([^\]]+)]\(\s*(?!https?:\/\/)(?:[^()\n]|\([^\n)]*\))*\)/gi, "$1")
    .replace(/^\[([^\]]+)]\(\s*(?!https?:\/\/)[^\n]*$/gim, "$1")
    .replace(/<[A-Za-z][^>\n]*(?:>|$)/g, "");
  const content = blockContent(marked.lexer(sanitized, { gfm: true }));
  return { type: "doc", content: content.length ? content : [{ type: "paragraph" }] };
}

const escapeText = (text: string): string => text
  .replace(/\\/g, "\\\\")
  .replace(/([*_])/g, "\\$1")
  .replace(/\[/g, "\\[")
  .replace(/]/g, "\\]");

function inlineMarkdown(nodes: JSONContent[] = []): string {
  return nodes.map((node) => {
    if (node.type !== "text") return "";
    let text = escapeText(node.text ?? "");
    const marks = node.marks ?? [];
    if (marks.some((mark) => mark.type === "bold")) text = `**${text}**`;
    if (marks.some((mark) => mark.type === "italic")) text = `*${text}*`;
    const link = marks.find((mark) => mark.type === "link");
    const href = typeof link?.attrs?.href === "string" ? link.attrs.href : "";
    if (isSafeArticleHref(href)) text = `[${text}](${href})`;
    return text;
  }).join("");
}

function listMarkdown(node: JSONContent, ordered: boolean): string {
  const start = typeof node.attrs?.start === "number" ? node.attrs.start : 1;
  return (node.content ?? []).map((item, index) => {
    const blocks = item.content ?? [];
    const first = blocks[0]?.type === "paragraph" ? inlineMarkdown(blocks[0].content) : "";
    const marker = ordered ? `${start + index}. ` : "- ";
    const nested = blocks.slice(1).map(blockMarkdown).filter(Boolean)
      .map((value) => value.split("\n").map((line) => `  ${line}`).join("\n"));
    return [marker + first, ...nested].join("\n");
  }).join("\n");
}

function blockMarkdown(node: JSONContent): string {
  switch (node.type) {
    case "paragraph":
      return inlineMarkdown(node.content);
    case "heading": {
      const level = node.attrs?.level === 3 ? 3 : 2;
      return `${"#".repeat(level)} ${inlineMarkdown(node.content)}`;
    }
    case "horizontalRule":
      return "---";
    case "blockquote":
      return (node.content ?? []).map(blockMarkdown).filter(Boolean).join("\n\n")
        .split("\n").map((line) => line ? `> ${line}` : ">").join("\n");
    case "bulletList":
      return listMarkdown(node, false);
    case "orderedList":
      return listMarkdown(node, true);
    default:
      return "";
  }
}

export function tiptapToCanonicalMarkdown(document: JSONContent): string {
  return (document.content ?? [])
    .map(blockMarkdown)
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

export function canonicalizeArticleMarkdown(markdown: string): string {
  return tiptapToCanonicalMarkdown(canonicalMarkdownToTiptap(markdown));
}

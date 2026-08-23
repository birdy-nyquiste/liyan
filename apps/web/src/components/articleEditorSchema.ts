import StarterKit from "@tiptap/starter-kit";

/** The one constrained Tiptap schema every 立言文章 projection uses. */
export const articleExtensions = [StarterKit.configure({
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

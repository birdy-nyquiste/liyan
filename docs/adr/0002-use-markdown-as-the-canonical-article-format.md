# Use Markdown as the canonical article format

Every saved article Revision uses a constrained Markdown subset as its canonical server-side body format. The 立言 Agent and Blog v0.11 API already exchange Markdown, while the workbench uses Tiptap for editing; keeping Tiptap's document model as a client projection avoids binding durable content to one editor and requires deterministic Markdown conversion and round-trip tests at the editor boundary.

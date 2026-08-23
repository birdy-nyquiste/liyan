import type { StartLiyanRunRequest } from "../api/client";
import { canonicalizeArticleMarkdown } from "./articleMarkdown";

export type LiyanWorkingCopy = NonNullable<StartLiyanRunRequest["working_copy"]>;

const keyFor = (userId: string, taskId: string) =>
  `liyan:working-copy:v1:${encodeURIComponent(userId)}:${encodeURIComponent(taskId)}`;

export function loadWorkingCopy(userId: string, taskId: string): LiyanWorkingCopy | null {
  try {
    const stored = window.localStorage.getItem(keyFor(userId, taskId));
    if (!stored) return null;
    const value: unknown = JSON.parse(stored);
    if (
      typeof value !== "object"
      || value === null
      || !("title" in value)
      || !("body_markdown" in value)
      || typeof value.title !== "string"
      || typeof value.body_markdown !== "string"
    ) return null;
    return {
      title: value.title,
      body_markdown: canonicalizeArticleMarkdown(value.body_markdown),
    };
  } catch {
    return null;
  }
}

export function saveWorkingCopy(
  userId: string,
  taskId: string,
  workingCopy: LiyanWorkingCopy,
): void {
  try {
    window.localStorage.setItem(keyFor(userId, taskId), JSON.stringify(workingCopy));
  } catch {
    // Browser storage can be unavailable or full. Editing must remain usable.
  }
}

import type { ExecutionResponse, ZhiyanStateResponse } from "../api/client";

/** One vocabulary for a run's state, shared by the report tab and the report. */
export const STATUS_LABELS: Record<ZhiyanStateResponse["status"], string> = {
  absent: "尚未分析",
  running: "分析进行中",
  cancelled: "分析已取消",
  failed: "分析未完成",
  succeeded: "分析已完成",
};

/**
 * How far a running 知言 has got, in the one sentence worth showing.
 *
 * Null until the run has actually done something: a run that has not reported
 * yet and a run that searched nothing are different, and "已检索 0 次" reads as
 * a stuck run rather than a starting one — which is the opposite of what this
 * line exists to say. The counts arrive on the Execution, so a finished run
 * keeps none of this; what a finished run did is in its 证据 section.
 */
export function searchProgressText(
  execution: ExecutionResponse | null | undefined,
  t: (source: string) => string,
): string | null {
  const progress = execution?.progress;
  if (!progress || progress.searched + progress.opened === 0) return null;
  return t("已检索 {searched} 次，已打开 {opened} 个页面")
    .replace("{searched}", String(progress.searched))
    .replace("{opened}", String(progress.opened));
}

import type { ZhiyanStateResponse } from "../api/client";

/** One vocabulary for a run's state, shared by the report tab and the report. */
export const STATUS_LABELS: Record<ZhiyanStateResponse["status"], string> = {
  absent: "尚未分析",
  running: "分析进行中",
  cancelled: "分析已取消",
  failed: "分析未完成",
  succeeded: "分析已完成",
};

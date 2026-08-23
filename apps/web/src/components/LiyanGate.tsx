import type { components } from "../api/schema";
import { useFocusWhen } from "./useFocusWhen";

type LiyanCapabilities = components["schemas"]["LiyanCapabilities"];

/**
 * The 立言 area of one 任务版本 while it is still shut.
 *
 * 立言 opens only once every 知言报告 of the current version has succeeded, and the
 * server alone decides that. Generating the article belongs to a later change;
 * what this owns is the gate, its reason, and taking focus the moment it opens.
 */
export function LiyanGate({
  liyan,
  headingId,
}: {
  liyan: LiyanCapabilities;
  headingId: string;
}) {
  const heading = useFocusWhen<HTMLHeadingElement>(liyan.can_generate);

  return (
    <section className="zhiyan-panel" aria-labelledby={headingId}>
      <p className="section-kicker">立言</p>
      <h3 id={headingId} ref={heading} tabIndex={-1}>
        立言文章
      </h3>
      <p className={liyan.can_generate ? "form-hint" : "form-error"} role="status">
        {liyan.can_generate
          ? "全部知言报告已完成，可以进入立言。"
          : liyan.unavailable_reason}
      </p>
    </section>
  );
}

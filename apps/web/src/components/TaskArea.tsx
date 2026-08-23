import type { ReactNode } from "react";

/**
 * One of the three task areas: 来源, 知言, 立言.
 *
 * A collapsed area still states where the work stands, so folding it away never
 * costs the reader the answer to "what is happening here". Only the expanded
 * area renders its body, which is what keeps three areas legible side by side.
 */
export function TaskArea({
  id,
  label,
  summary,
  expanded,
  onExpand,
  children,
}: {
  id: string;
  label: string;
  summary: string | null;
  expanded: boolean;
  onExpand(): void;
  children: ReactNode;
}) {
  return (
    <section
      className="task-area"
      data-state={expanded ? "expanded" : "collapsed"}
      aria-labelledby={`${id}-label`}
    >
      <button
        className="task-area__toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls={`${id}-body`}
        onClick={onExpand}
      >
        <span className="task-area__label" id={`${id}-label`}>{label}</span>
        {summary ? <span className="task-area__summary">{summary}</span> : null}
      </button>
      {expanded ? (
        <div className="task-area__body" id={`${id}-body`}>{children}</div>
      ) : null}
    </section>
  );
}

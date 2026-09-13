/**
 * What a run looks like while it runs.
 *
 * Provider work in this workbench takes minutes and puts nothing on screen
 * while it does, so every one of them says so in the place its result will
 * appear — a source being read, a 知言 report being written, a 立言 article
 * being drafted. One notice, so a writer learns it once.
 *
 * `detail` is the second thing a writer wants after "is it running": whether it
 * is getting anywhere. Only the runs that check 来源 against the web have an
 * answer, so it is optional, and it sits below the label rather than replacing
 * it — the label is what this is, the detail is only how far along.
 */
export function RunningNotice({ label, detail }: { label: string; detail?: string }) {
  return (
    <p className="running-notice" role="status">
      <span className="running-notice__bar" aria-hidden="true" />
      <span className="running-notice__text">
        {label}
        {detail ? <span className="running-notice__detail">{detail}</span> : null}
      </span>
    </p>
  );
}

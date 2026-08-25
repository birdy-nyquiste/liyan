/**
 * What a run looks like while it runs.
 *
 * Provider work in this workbench takes minutes and puts nothing on screen
 * while it does, so every one of them says so in the place its result will
 * appear — a source being read, a 知言 report being written, a 立言 article
 * being drafted. One notice, so a writer learns it once.
 */
export function RunningNotice({ label }: { label: string }) {
  return (
    <p className="running-notice" role="status">
      <span className="running-notice__bar" aria-hidden="true" />
      {label}
    </p>
  );
}

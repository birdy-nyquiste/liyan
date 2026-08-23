import type { LiyanWorkingCopy } from "./workingCopyStorage";

/**
 * The identity the server assigns to saved article content.
 *
 * It must stay byte-identical to `article_content_hash` on the server: SHA-256 over
 * a JSON object with sorted keys, no whitespace, and unescaped non-ASCII text. The
 * browser sends it so the server, not the workbench, decides whether a Revision is
 * still publishable or the draft carries unsaved edits.
 */
export async function articleContentHash(workingCopy: LiyanWorkingCopy): Promise<string> {
  const canonical = JSON.stringify({
    body_markdown: workingCopy.body_markdown.trim(),
    title: workingCopy.title.trim(),
  });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * The workbench's mirror of the rule the server applies to `working_copy_hash`.
 *
 * A read carries the draft's hash, so the server decides eligibility whenever it
 * answers. Between reads the draft can drift, and an edit must withdraw the badge
 * without waiting for the next poll — so the same comparison runs here, against
 * the Revision hash the server issued. A draft whose hash has not been computed
 * yet counts as drifted: eligibility is never claimed on missing evidence.
 */
export function draftMatchesRevision(
  workingCopy: LiyanWorkingCopy | null,
  workingCopyHash: string | null,
  revisionContentHash: string | null,
): boolean {
  if (workingCopy === null) return true;
  return workingCopyHash !== null && workingCopyHash === revisionContentHash;
}

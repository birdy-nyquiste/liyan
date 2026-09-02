/**
 * Only a plain web address may become a link; anything else stays inert text.
 *
 * Evidence URLs come from a provider, and a report is read by someone deciding
 * whether to trust it — so a `javascript:` or `data:` address must render as
 * what it is rather than as something clickable.
 */
export function webAddress(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

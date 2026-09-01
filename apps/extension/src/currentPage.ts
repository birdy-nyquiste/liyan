/**
 * The page the user is looking at, and whether 立言阁 could ever fetch it.
 *
 * The check is here as well as on the server so that the button can be dead
 * before it is pressed. A refusal the panel could have predicted costs the user
 * a click and tells them afterwards; this is the same rule, arriving earlier.
 * The server's `normalize_public_url` remains the authority — this never admits
 * anything it would reject, and is allowed to be the cruder of the two.
 */

export type CurrentPage = {
  /** The tab's address, whatever it is. */
  url: string;
  /** The same address in the server's normalized form, for comparing. */
  normalizedUrl: string;
  /** The title Chrome has for the tab, which may be nothing. */
  title: string;
  /** Null when 立言阁 could fetch it; otherwise why it cannot. */
  refusal: string | null;
};

/**
 * A URL in the form the server stores it, so two spellings of one page compare
 * equal. This mirrors `normalize_public_url`: lowercased host, no default port,
 * an empty path becomes `/`, the fragment is dropped, the query is kept. It
 * exists so the panel can tell that a page is already in the basket, which it
 * knows only by the `provenance` the server wrote — and that is normalized.
 */
export function normalizeUrl(value: string): string {
  try {
    const parsed = new URL(value);
    const isDefaultPort =
      (parsed.protocol === "https:" && parsed.port === "443") ||
      (parsed.protocol === "http:" && parsed.port === "80");
    const host = isDefaultPort ? parsed.hostname.toLowerCase() : parsed.host.toLowerCase();
    return `${parsed.protocol}//${host}${parsed.pathname || "/"}${parsed.search}`;
  } catch {
    return value;
  }
}

const NOT_PUBLIC = "当前页面不是公开网址，无法作为来源抓取。";

/** Whether a hostname names something only this machine or network can reach. */
function isPrivateHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "[::1]" || host === "0.0.0.0") return true;
  // The private IPv4 ranges, plus link-local. Written out rather than parsed:
  // the server does the real work, and a regex that is wrong in the strict
  // direction only costs a user a button they could have pressed.
  return /^(10|127)\./.test(host) || /^192\.168\./.test(host) || /^169\.254\./.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(host);
}

export function describePage(url: string | undefined, title: string | undefined): CurrentPage {
  const address = url ?? "";
  const named = title?.trim() || address;
  let parsed: URL;
  try {
    parsed = new URL(address);
  } catch {
    return { url: address, normalizedUrl: address, title: named, refusal: NOT_PUBLIC };
  }
  const normalizedUrl = normalizeUrl(address);
  // chrome://, file://, and the Web Store are not merely private — a panel
  // cannot even see them. Everything that is not http(s) fails here together.
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { url: address, normalizedUrl, title: named, refusal: NOT_PUBLIC };
  }
  if (!parsed.hostname || parsed.username || parsed.password || isPrivateHost(parsed.hostname)) {
    return { url: address, normalizedUrl, title: named, refusal: NOT_PUBLIC };
  }
  return { url: address, normalizedUrl, title: named, refusal: null };
}

/** What the user is looking at right now, or nothing when there is no tab. */
export async function readCurrentPage(): Promise<CurrentPage> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return describePage(tab?.url, tab?.title);
}

/** The address as a person reads it: host, then path, without the scheme. */
export function shortenUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.host}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    return url;
  }
}

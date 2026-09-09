/**
 * Whether the addresses a build was given are ones a published package may
 * carry, and if not, why not.
 *
 * `package` produces the file that gets uploaded, and the addresses of 立言阁
 * reach it from a gitignored `.env.production` that a checkout cannot be
 * relied on to have. Without a check, the missing file is not an error: `.env`
 * answers instead, and the build succeeds with a localhost API and a real
 * Supabase project — an extension that installs, signs a user in, and then
 * cannot make a single request. The README asks for the manifest to be read
 * before uploading, but that is a habit, and this is the same rule as a
 * mechanism.
 *
 * `VITE_WEB_BASE_URL` is checked here even though it appears nowhere in the
 * manifest, which is exactly why: it is compiled into the bundle instead, so
 * reading the manifest cannot catch it, and 打开任务 pointed at localhost:5173
 * is as broken as an API pointed at localhost:8000.
 */

/** The three addresses a build of the 插件 is aimed at. */
export type BuildTarget = {
  /** `VITE_API_BASE_URL` — the API, and a `host_permissions` entry. */
  apiBaseUrl: string | undefined;
  /** `VITE_WEB_BASE_URL` — where 购买额度 and 打开任务 send the user. */
  webBaseUrl: string | undefined;
  /** `VITE_SUPABASE_URL` — sign-in, and a `host_permissions` entry. */
  supabaseUrl: string | undefined;
};

/**
 * Hosts that name something only the packager's own machine or network can
 * reach.
 *
 * Deliberately not shared with `src/currentPage.ts`, which asks a similar
 * question for a different reason: that one predicts a refusal the server will
 * make about a page, and is allowed to be crude in the strict direction. This
 * one decides whether a release may exist, and being wrong in either direction
 * costs something real. Neither should quietly inherit the other's rules.
 */
function isUnreachableHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "::1" || host === "[::1]" || host === "0.0.0.0") return true;
  if (/^(10|127)\./.test(host)) return true;
  if (/^192\.168\./.test(host)) return true;
  if (/^169\.254\./.test(host)) return true;
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(host)) return true;
  // A host with no dot in it is not a name public DNS can answer. It is how an
  // intranet address looks, and how a half-edited one looks too.
  return !host.includes(".");
}

/** The name of the variable each address arrives in, for the message. */
const VARIABLE: Record<keyof BuildTarget, string> = {
  apiBaseUrl: "VITE_API_BASE_URL",
  webBaseUrl: "VITE_WEB_BASE_URL",
  supabaseUrl: "VITE_SUPABASE_URL",
};

function refusalFor(field: keyof BuildTarget, value: string | undefined): string | null {
  const variable = VARIABLE[field];
  if (!value) return `${variable} is not set.`;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return `${variable} is not a URL: ${value}`;
  }
  // http would work for the API — `host_permissions` accepts it and Chrome
  // would allow the request. It is refused anyway: every installer's session
  // token would cross the network in the clear, and there is no deployment of
  // 立言阁 this could be the right answer for.
  if (parsed.protocol !== "https:") {
    return `${variable} is not https, so it cannot be a published address: ${value}`;
  }
  if (isUnreachableHost(parsed.hostname)) {
    return `${variable} names a host only this machine can reach: ${value}`;
  }
  return null;
}

/**
 * Every reason this target cannot be published, or an empty list when it can.
 *
 * All of them rather than the first: a checkout with no `.env.production` has
 * three problems, and being told them one build at a time is three builds.
 */
export function releaseRefusals(target: BuildTarget): string[] {
  return (Object.keys(VARIABLE) as (keyof BuildTarget)[])
    .map((field) => refusalFor(field, target[field]))
    .filter((refusal): refusal is string => refusal !== null);
}

/**
 * The message a release build fails with, or null when it may proceed.
 *
 * Written as a whole message rather than thrown here so that the caller owns
 * how the build stops, and so this stays a function of its input.
 */
export function releaseRefusal(target: BuildTarget): string | null {
  const refusals = releaseRefusals(target);
  if (refusals.length === 0) return null;
  return [
    "This build is not fit to publish:",
    ...refusals.map((line) => `  - ${line}`),
    "",
    "`package` builds the file that gets uploaded, so it reads .env.production",
    "from the repository root. That file is gitignored; create it as",
    "apps/extension/README.md describes, or pass the values on the command line.",
    "To build against a local 立言阁, use `npm run build:extension` instead.",
  ].join("\n");
}

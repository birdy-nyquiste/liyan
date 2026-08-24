import * as Sentry from "@sentry/react";

/**
 * Error reporting that never carries what the user is writing.
 *
 * This browser holds 来源 bodies, 知言报告, and the article being drafted —
 * ADR-0003 keeps the working copy here on purpose. Sentry captures whatever the
 * page was holding when something broke, so an unfiltered report would ship all
 * of it to a third party the user never agreed to.
 *
 * The rule is subtractive and explicit: strip every carrier of content, keep the
 * exception and the identities needed to act on it. Nothing is left to a default
 * that a future SDK version might change.
 */

/** The parts of a Sentry event this code inspects, named so tests can build one. */
export type ScrubbableEvent = {
  request?: {
    url?: string;
    data?: unknown;
    headers?: Record<string, string>;
    cookies?: unknown;
  };
  user?: { id?: string; email?: string; username?: string; ip_address?: string };
  breadcrumbs?: Array<{ category?: string; message?: string; data?: unknown }>;
  exception?: { values?: Array<{ type?: string; value?: string }> };
  extra?: unknown;
  contexts?: unknown;
};

/** Headers worth keeping. Anything that authenticates is not among them. */
const SAFE_HEADERS = new Set(["content-type", "accept", "user-agent"]);

export function scrubEvent(event: ScrubbableEvent): ScrubbableEvent | null {
  const scrubbed: ScrubbableEvent = { ...event };

  if (scrubbed.request) {
    const { url, headers } = scrubbed.request;
    scrubbed.request = {
      // A query string is a place content ends up by accident. The path alone
      // says which endpoint failed, which is all an error report needs.
      ...(url ? { url: url.split("?")[0] } : {}),
      ...(headers ? { headers: keepSafeHeaders(headers) } : {}),
    };
  }

  if (scrubbed.user) {
    // An id is enough to find the account. An address is personal data with no
    // diagnostic value here.
    scrubbed.user = scrubbed.user.id ? { id: scrubbed.user.id } : undefined;
  }

  if (scrubbed.breadcrumbs) {
    // The trail of what happened is useful; the payloads it carried are the
    // request bodies again by another name.
    scrubbed.breadcrumbs = scrubbed.breadcrumbs.map(({ category, message }) => ({
      ...(category ? { category } : {}),
      ...(message ? { message } : {}),
    }));
  }

  if (scrubbed.exception?.values) {
    // The type, never the message. A parse or validation error quotes what it
    // was handed, which here is 来源 text or the article being written — the
    // same reason the server's log formatter keeps only the exception type.
    scrubbed.exception = {
      values: scrubbed.exception.values.map(({ type }) => ({ type })),
    };
  }

  // Free-form buckets: anything may have been put here, so nothing leaves.
  delete scrubbed.extra;
  delete scrubbed.contexts;

  return scrubbed;
}

function keepSafeHeaders(headers: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).filter(([name]) => SAFE_HEADERS.has(name.toLowerCase())),
  );
}

export type MonitoringOptions = {
  dsn: string;
  sendDefaultPii: false;
  beforeSend: (event: ScrubbableEvent) => ScrubbableEvent | null;
  beforeBreadcrumb: (crumb: { data?: unknown }) => { data?: unknown };
};

/**
 * How Sentry should be configured, or `null` when it should not run at all.
 *
 * No DSN means no reporting: local development and the test suite send nothing
 * anywhere, and an environment that forgot to configure monitoring degrades to
 * silence rather than to an error at startup.
 */
export function monitoringOptions(dsn: string | undefined): MonitoringOptions | null {
  if (!dsn) return null;
  return {
    dsn,
    // Belt as well as braces: `beforeSend` scrubs, and this stops the SDK
    // gathering addresses and cookies in the first place.
    sendDefaultPii: false,
    beforeSend: scrubEvent,
    beforeBreadcrumb: (crumb) => {
      const kept = { ...crumb };
      delete kept.data;
      return kept;
    },
  };
}

export function initialiseMonitoring(dsn: string | undefined): void {
  const options = monitoringOptions(dsn);
  if (options === null) return;
  Sentry.init(options as Parameters<typeof Sentry.init>[0]);
}

import { describe, expect, it } from "vitest";

import { monitoringOptions, scrubEvent } from "./monitoring";

/**
 * Sentry sees whatever the browser was holding when something broke, and this
 * browser holds 来源 bodies, 知言报告, and the article the user is writing. An
 * error report is worth having; the draft inside it is not worth sending.
 */
describe("scrubEvent", () => {
  it("drops the request body, which is where article and source text travels", () => {
    const scrubbed = scrubEvent({
      request: {
        url: "https://liyan.example/publication/publish-tasks",
        data: { title: "四天工作制的真问题", body_markdown: "正文" },
      },
    });

    expect(scrubbed?.request?.data).toBeUndefined();
    expect(JSON.stringify(scrubbed)).not.toContain("正文");
  });

  it("keeps the URL path but never its query, which can carry anything", () => {
    const scrubbed = scrubEvent({
      request: { url: "https://liyan.example/tasks?draft=%E6%AD%A3%E6%96%87" },
    });

    expect(scrubbed?.request?.url).toBe("https://liyan.example/tasks");
  });

  it("removes the authorization header rather than trusting a default", () => {
    const scrubbed = scrubEvent({
      request: {
        url: "https://liyan.example/tasks",
        headers: { Authorization: "Bearer supabase-token", "Content-Type": "application/json" },
      },
    });

    expect(scrubbed?.request?.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("reports who hit the error by id, and says nothing else about them", () => {
    const scrubbed = scrubEvent({
      user: { id: "user-1", email: "writer@example.com", username: "writer" },
    });

    expect(scrubbed?.user).toEqual({ id: "user-1" });
  });

  it("keeps breadcrumbs as events without the data they carried", () => {
    const scrubbed = scrubEvent({
      breadcrumbs: [
        { category: "fetch", message: "POST /liyan-revisions", data: { body: "正文" } },
      ],
    });

    expect(scrubbed?.breadcrumbs?.[0].category).toBe("fetch");
    expect(scrubbed?.breadcrumbs?.[0].data).toBeUndefined();
    expect(JSON.stringify(scrubbed)).not.toContain("正文");
  });

  it("keeps the exception type and drops its message, which quotes content", () => {
    const scrubbed = scrubEvent({
      exception: {
        values: [{ type: "SyntaxError", value: "Unexpected token in 来源正文" }],
      },
    });

    expect(scrubbed?.exception?.values?.[0].type).toBe("SyntaxError");
    expect(scrubbed?.exception?.values?.[0].value).toBeUndefined();
    expect(JSON.stringify(scrubbed)).not.toContain("来源正文");
  });
});

describe("monitoringOptions", () => {
  it("stays off when no DSN is configured, so local and test runs send nothing", () => {
    expect(monitoringOptions("")).toBeNull();
    expect(monitoringOptions(undefined)).toBeNull();
  });

  it("refuses to attach request bodies even before scrubbing runs", () => {
    const options = monitoringOptions("https://key@sentry.example/1");

    expect(options).not.toBeNull();
    expect(options?.sendDefaultPii).toBe(false);
    expect(options?.dsn).toBe("https://key@sentry.example/1");
  });
});

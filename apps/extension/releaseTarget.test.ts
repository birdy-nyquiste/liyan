import { describe, expect, it } from "vitest";

import { releaseRefusal, releaseRefusals } from "./releaseTarget";

const publishable = {
  apiBaseUrl: "https://api.liyan.example.com",
  webBaseUrl: "https://liyan.example.com",
  supabaseUrl: "https://project.supabase.co",
};

describe("releaseRefusals", () => {
  it("has nothing to say about a target that is fit to publish", () => {
    expect(releaseRefusals(publishable)).toEqual([]);
    expect(releaseRefusal(publishable)).toBeNull();
  });

  it("refuses the defaults a checkout without .env.production falls back to", () => {
    // The failure this exists for. `.env` answers when `.env.production` is
    // missing, and it holds a localhost API, a localhost 工作台 and a real
    // Supabase project — so the build succeeds and the package is broken.
    const refusals = releaseRefusals({
      apiBaseUrl: "http://localhost:8000",
      webBaseUrl: "http://localhost:5173",
      supabaseUrl: "https://project.supabase.co",
    });
    expect(refusals).toHaveLength(2);
    expect(refusals.join("\n")).toContain("VITE_API_BASE_URL");
    expect(refusals.join("\n")).toContain("VITE_WEB_BASE_URL");
  });

  it("says every wrong thing at once rather than one build at a time", () => {
    expect(
      releaseRefusals({ apiBaseUrl: undefined, webBaseUrl: undefined, supabaseUrl: undefined }),
    ).toHaveLength(3);
  });

  it("refuses http even where Chrome would have allowed it", () => {
    expect(
      releaseRefusals({ ...publishable, apiBaseUrl: "http://api.liyan.example.com" }).join(),
    ).toContain("not https");
  });

  it("refuses a private address, and a bare host that public DNS cannot answer", () => {
    for (const apiBaseUrl of [
      "https://192.168.1.10",
      "https://10.0.0.4",
      "https://172.16.0.9",
      "https://127.0.0.1",
      "https://api.localhost",
      "https://liyan-api",
    ]) {
      expect(releaseRefusals({ ...publishable, apiBaseUrl })).toHaveLength(1);
    }
  });

  it("refuses something that is not a URL at all", () => {
    expect(releaseRefusals({ ...publishable, webBaseUrl: "liyan.example.com" }).join()).toContain(
      "not a URL",
    );
  });

  it("allows a public host on a non-default port, which staging may well use", () => {
    expect(releaseRefusals({ ...publishable, apiBaseUrl: "https://api.example.com:8443" })).toEqual(
      [],
    );
  });

  it("says what to do about it, not only that it is wrong", () => {
    const message = releaseRefusal({ ...publishable, apiBaseUrl: "http://localhost:8000" });
    expect(message).toContain(".env.production");
    expect(message).toContain("npm run build:extension");
  });
});

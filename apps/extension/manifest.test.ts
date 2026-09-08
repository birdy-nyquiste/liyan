import { describe, expect, it } from "vitest";

import { buildManifest } from "./manifest";

/**
 * The manifest is the one file in the package that cannot be corrected quietly.
 *
 * Widening `permissions` or `host_permissions` in an update does not just ship
 * a change: Chrome disables the extension for every existing user until they
 * re-accept the new warning. So what these tests pin is not that the builder
 * works — it is the install surface itself, which should not be able to grow
 * without someone editing this file and saying why.
 */

const environment = {
  apiBaseUrl: "https://api.example.com",
  supabaseUrl: "https://project.supabase.co",
  webBaseUrl: "https://liyan.example.com",
  version: "1.0.0",
};

describe("buildManifest", () => {
  it("asks for activeTab and storage, and nothing else", () => {
    expect(buildManifest(environment).permissions).toEqual(["activeTab", "storage"]);
  });

  it("asks for 立言阁's own two hosts, and nothing else", () => {
    expect(buildManifest(environment).host_permissions).toEqual([
      "https://api.example.com/*",
      "https://project.supabase.co/*",
    ]);
  });

  it("declares nothing that reaches a page the user is browsing", () => {
    // A content script, a background worker and `web_accessible_resources` are
    // each a different way for the extension to touch pages it has no business
    // touching. The design says it has none of them; this is that in a test.
    const manifest: Record<string, unknown> = buildManifest(environment);
    expect(manifest.content_scripts).toBeUndefined();
    expect(manifest.background).toBeUndefined();
    expect(manifest.web_accessible_resources).toBeUndefined();
    expect(manifest.optional_permissions).toBeUndefined();
    expect(manifest.optional_host_permissions).toBeUndefined();
  });

  it("keeps only the origin of each address, whatever path it arrived with", () => {
    // `VITE_API_BASE_URL` is allowed to carry a path — a match pattern's path
    // is a filter, so keeping it would narrow the permission to that one path
    // and every other call would be blocked.
    const withPaths = buildManifest({
      ...environment,
      apiBaseUrl: "https://api.example.com/v1",
      supabaseUrl: "https://project.supabase.co/auth/",
    });
    expect(withPaths.host_permissions).toEqual([
      "https://api.example.com/*",
      "https://project.supabase.co/*",
    ]);
  });

  it("keeps the port, which is what makes a local build loadable", () => {
    // Chrome's match patterns take a port, and omitting one means every port.
    // A local API on :8000 therefore has to keep it, or the pattern would ask
    // for something wider than the build needs.
    expect(
      buildManifest({ ...environment, apiBaseUrl: "http://localhost:8000" }).host_permissions,
    ).toEqual(["http://localhost:8000/*", "https://project.supabase.co/*"]);
  });

  it("takes its version from the package, where the release notes bump it", () => {
    expect(buildManifest({ ...environment, version: "1.2.3" }).version).toBe("1.2.3");
  });

  it("names the oldest Chrome the build actually runs in", () => {
    // Pinned to the same number as `build.target`. If one moves, this fails
    // and the other has to move with it.
    expect(buildManifest(environment).minimum_chrome_version).toBe("111");
  });

  it("points its homepage at the root of 工作台, not at a path inside it", () => {
    expect(buildManifest(environment).homepage_url).toBe("https://liyan.example.com/");
    expect(
      buildManifest({ ...environment, webBaseUrl: "https://liyan.example.com/task" }).homepage_url,
    ).toBe("https://liyan.example.com/");
  });

  it("is manifest v3, with the popup and every icon size Chrome asks for", () => {
    const manifest = buildManifest(environment);
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.action.default_popup).toBe("popup.html");
    expect(Object.keys(manifest.icons)).toEqual(["16", "32", "48", "128"]);
  });

  it("describes itself within the 132 characters the Web Store allows", () => {
    const manifest = buildManifest(environment);
    expect(manifest.description.length).toBeLessThanOrEqual(132);
    expect(manifest.name.length).toBeLessThanOrEqual(75);
  });
});

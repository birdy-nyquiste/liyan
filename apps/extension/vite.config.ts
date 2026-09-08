import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { loadEnv, type Plugin } from "vite";
import { defineConfig } from "vitest/config";

import { buildManifest } from "./manifest";
import { releaseRefusal } from "./releaseTarget";
import packageJson from "./package.json" with { type: "json" };

/**
 * Set by `npm run package`, and by nothing else.
 *
 * `vite build` is how the extension is built for everyday work *and* how the
 * uploaded package is made — `dev` is the same command with `--watch`, and all
 * of them run in production mode. So the mode cannot tell a release apart from
 * a local build, and the script that makes the release says so instead.
 */
const RELEASE_FLAG = "LIYAN_EXTENSION_RELEASE";

/**
 * The workbench's source, imported rather than copied.
 *
 * The 插件 signs in with the same component, the same strings, and the same
 * stylesheet as 工作台 — see `docs/design/the-browser-extension.md`. Aliasing
 * the source is what keeps that a fact rather than an intention: a change to
 * `AuthPanel` reaches both, and there is no second copy to forget.
 */
const workbench = fileURLToPath(new URL("../web/src", import.meta.url));

/**
 * What 工作台 serves as static files, the mark among them.
 *
 * Separate from the source alias because it is a different kind of thing: the
 * panel imports the mark so that there is one file, and 工作台 changing it
 * changes the panel too. The toolbar icons are PNGs rasterized from this same
 * source, which Chrome requires and cannot be an import.
 */
const workbenchAssets = fileURLToPath(new URL("../web/public", import.meta.url));

/** Emit `manifest.json` beside the build, pointed at this build's servers. */
function manifest(mode: string): Plugin {
  return {
    name: "liyan-manifest",
    generateBundle() {
      const env = loadEnv(mode, fileURLToPath(new URL("../..", import.meta.url)), "VITE_");
      const apiBaseUrl = env.VITE_API_BASE_URL ?? "http://localhost:8000";
      const webBaseUrl = env.VITE_WEB_BASE_URL ?? "http://localhost:5173";
      const supabaseUrl = env.VITE_SUPABASE_URL;
      // A release is held to every address being publishable. It is checked
      // first because its message says which values are wrong and how to fix
      // them, which is more use than the one below.
      if (process.env[RELEASE_FLAG]) {
        const refusal = releaseRefusal({ apiBaseUrl, webBaseUrl, supabaseUrl });
        if (refusal) throw new Error(refusal);
      }
      if (!supabaseUrl) {
        // Failing the build is the point: a manifest without Supabase's host
        // produces an extension that installs and then cannot sign anybody in.
        throw new Error("VITE_SUPABASE_URL is required to build the extension.");
      }
      this.emitFile({
        type: "asset",
        fileName: "manifest.json",
        source: JSON.stringify(
          buildManifest({ apiBaseUrl, supabaseUrl, webBaseUrl, version: packageJson.version }),
          null,
          2,
        ),
      });
    },
  };
}

export default defineConfig(({ mode }) => ({
  // The same root .env the workbench reads, so both clients point at one
  // Supabase project and one API without a second place to keep them in step.
  envDir: "../..",
  plugins: [react(), tailwindcss(), manifest(mode)],
  resolve: { alias: { "@workbench": workbench, "@workbench-assets": workbenchAssets } },
  build: {
    // Chrome loads an unpacked directory, so the output is the extension.
    outDir: "dist",
    emptyOutDir: true,
    // One browser, one version, and the same one `minimum_chrome_version`
    // claims. Left at Vite's default this tracks whatever "widely available"
    // means on the day of the build, which is not something a published
    // manifest can promise on behalf of a future checkout.
    target: "chrome111",
    rollupOptions: { input: fileURLToPath(new URL("./popup.html", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
}));

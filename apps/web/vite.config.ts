import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  envDir: "../..",
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // The Playwright suite drives a browser and a server; Vitest would collect
    // its specs by name and run them in jsdom, where they cannot mean anything.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});

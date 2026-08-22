import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("server health", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows that the server is alive through the generated API client", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "alive" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    render(<App />);

    expect(await screen.findByText("服务正常")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        method: "GET",
        url: "http://localhost:8000/health/live",
      }),
    );
  });

  it("shows a safe unavailable state when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(await screen.findByText("服务暂不可用")).toBeInTheDocument();
  });
});

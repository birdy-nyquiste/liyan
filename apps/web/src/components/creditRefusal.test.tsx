import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ApiError, refusalWithoutTiming } from "../api/client";
import { BuyCreditsLink } from "./BuyCreditsLink";
import { INSUFFICIENT_CREDITS, PAID_ONLY, isCreditRefusal } from "./creditRefusal";

describe("额度不足", () => {
  it("reaches the workbench at all, which it did not before", () => {
    // 402 was the one refusal nothing read: every entry point fell back to a
    // generic failure, which sends a user to support instead of to /account.
    const refused = new ApiError(402, INSUFFICIENT_CREDITS);

    expect(refusalWithoutTiming(refused)).toBe(INSUFFICIENT_CREDITS);
  });

  it("carries no timing, because waiting fixes nothing about an empty balance", () => {
    // The sibling 429 is a queue to wait out and says so with Retry-After.
    // This one is not, and a countdown here would name a moment at which
    // nothing will have changed.
    const refused = new ApiError(402, INSUFFICIENT_CREDITS, null);

    expect(refused.retryAfterSeconds).toBeNull();
    expect(refusalWithoutTiming(refused)).toBe(INSUFFICIENT_CREDITS);
  });

  it("distinguishes a balance that is short from a 来源 kind that is locked", () => {
    expect(isCreditRefusal(INSUFFICIENT_CREDITS)).toBe(true);
    expect(isCreditRefusal(PAID_ONLY)).toBe(true);
    expect(isCreditRefusal("分析服务暂时不可用。")).toBe(false);
  });

  it("offers the one thing that would fix it", () => {
    // Never a bare failure. A refusal a user cannot act on has told them off
    // rather than told them something.
    render(
      <MemoryRouter>
        <BuyCreditsLink />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "购买额度" })).toHaveAttribute("href", "/account");
  });
});

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

document.elementFromPoint = () => document.body;
Range.prototype.getBoundingClientRect = () => new DOMRect();
Range.prototype.getClientRects = () => ({
  length: 0,
  item: () => null,
  [Symbol.iterator]: () => [][Symbol.iterator](),
}) as DOMRectList;

afterEach(() => {
  cleanup();
  // Stored preferences (locale, theme, folded sections) would otherwise leak
  // from one test into the next.
  window.localStorage.clear();
});

import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
configure({ asyncUtilTimeout: 5000 });
afterEach(() => cleanup());
// jsdom lacks these; Recharts / layout code touches them.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? RO;
window.matchMedia =
  window.matchMedia ??
  ((q) => ({
    matches: false,
    media: q,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent: () => false,
  }));
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
// jsdom has no layout, so ResponsiveContainer would measure 0x0 and draw nothing. Give charts a fixed size.
import { cloneElement, createElement } from "react";
import { vi } from "vitest";
vi.mock("recharts", async (importOriginal) => {
  const real = await importOriginal();
  return {
    ...real,
    ResponsiveContainer: ({ children }) =>
      createElement("div", { style: { width: 800, height: 300 } }, cloneElement(children, { width: 800, height: 300 })),
  };
});

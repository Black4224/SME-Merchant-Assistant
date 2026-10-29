import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AppRoutes } from "../App";
import { ToastProvider } from "../components/Toast";
import { SettingsProvider } from "../lib/settings";
import categories from "./fixtures/categories.json";
import customers from "./fixtures/customers.json";
import settings from "./fixtures/settings.json";
import suppliers from "./fixtures/suppliers.json";
export const fail = (status, code, message, details) => ({ __status: status, body: { error: { code, message, details } } });
/** Route-based fetch mock. Key = "METHOD /path" (query string ignored). Records every request. */
export function mockFetch(routes) {
  const calls = [];
  const fn = vi.fn(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const call = {
      method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      form: init?.body instanceof FormData ? init.body : null,
    };
    calls.push(call);
    const h = routes[`${method} ${url.pathname}`];
    const json = (b, status = 200) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });
    if (h === undefined) return json({ error: { code: "unmocked", message: `unmocked ${method} ${url.pathname}` } }, 404);
    const out = typeof h === "function" ? await h(call) : h;
    return out && typeof out === "object" && "__status" in out ? json(out.body, out.__status) : json(out);
  });
  vi.stubGlobal("fetch", fn);
  return {
    calls,
    fn,
    of: (method, path) => calls.filter((c) => c.method === method && c.path === path),
  };
}
export const baseRoutes = () => ({
  "GET /api/settings": settings,
  "GET /api/customers": customers,
  "GET /api/suppliers": suppliers,
  "GET /api/categories": categories,
});
export function renderAt(path, ui) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SettingsProvider>
        <ToastProvider>{ui ?? <AppRoutes />}</ToastProvider>
      </SettingsProvider>
    </MemoryRouter>,
  );
}

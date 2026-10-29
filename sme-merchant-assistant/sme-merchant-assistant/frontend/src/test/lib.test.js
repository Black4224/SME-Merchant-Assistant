import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, buildQuery, request } from "../api/client";
import { fmtDate, fmtIqd, fmtNum, fmtPct, parseAmountInput } from "../lib/format";
describe("format", () => {
  it("formats money with a real minus sign and Latin digits", () => {
    expect(fmtNum(-1500)).toBe("\u22121,500");
    expect(fmtIqd(1250000)).toBe("1,250,000 د.ع");
    expect(fmtIqd(-5, "IQD")).toBe("\u22125 IQD");
    expect(fmtNum(0)).toBe("0");
  });
  it("formats dates in Arabic with Latin digits (no Arabic-Indic numerals)", () => {
    const s = fmtDate("2026-10-15");
    expect(s).toMatch(/2026/);
    expect(s).toMatch(/15/);
    expect(s).not.toMatch(/[٠-٩]/);
    expect(fmtDate(null)).toBe("—");
    expect(fmtDate("garbage")).toBe("—");
  });
  it("formats percent changes, including the undefined case", () => {
    expect(fmtPct("50.0")).toBe("+50%");
    expect(fmtPct("-12.5")).toBe("\u221212.5%");
    expect(fmtPct("0.0")).toBe("0%");
    expect(fmtPct(null)).toBe("غير محسوب");
  });
  it.each([
    ["1,250,000", 1250000],
    ["١٢٥٠٠٠٠", 1250000],
    ["١٬٢٥٠٬٠٠٠", 1250000],
    ["1250000.00", 1250000],
    ["1 250 000 د.ع", 1250000],
    ["5", 5],
  ])("parseAmountInput accepts %s", (text, expected) => expect(parseAmountInput(text)).toBe(expected));
  it.each(["", "  ", "0", "-5", "1500.5", "abc", "1e3", "NaN", "100000000001"])(
    "parseAmountInput rejects %j (mirrors the backend)",
    (text) => expect(parseAmountInput(text)).toBeNull(),
  );
});
const err = async (p) =>
  await p.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (x) => x,
  );
describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());
  const respond = (status, body, raw) =>
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(raw ?? JSON.stringify(body), { status })),
    );
  it("builds query strings without empty values", () => {
    expect(buildQuery({ a: "x", b: "", c: undefined, d: null, e: 0, f: false })).toBe("?a=x&e=0&f=false");
    expect(buildQuery({})).toBe("");
    expect(buildQuery(undefined)).toBe("");
  });
  it("returns parsed JSON on success", async () => {
    respond(200, { ok: 1 });
    expect(await request("/api/x")).toEqual({ ok: 1 });
  });
  it("maps the backend error format to ApiError with field errors", async () => {
    respond(422, {
      error: { code: "validation_error", message: "بيانات غير صالحة", details: [{ field: "amount", message: "المبلغ خاطئ" }] },
    });
    const e = await err(request("/api/x"));
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 422, code: "validation_error", message: "بيانات غير صالحة" });
    expect(e.fieldErrors).toEqual({ amount: "المبلغ خاطئ" });
  });
  it("turns a network failure into a clear Arabic error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const e = await err(request("/api/x"));
    expect(e).toMatchObject({ status: 0, code: "network" });
    expect(e.message).toContain("تعذّر الاتصال بالخادم");
  });
  it("handles a non-JSON error body without crashing", async () => {
    respond(502, undefined, "<html>Bad gateway</html>");
    const e = await err(request("/api/x"));
    expect(e).toMatchObject({ status: 502, code: "http_error" });
    expect(e.message).toContain("502");
  });
  it("sends JSON bodies with the right header and FormData untouched", async () => {
    const f = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", f);
    await request("/api/x", { method: "POST", body: { a: 1 } });
    expect(f.mock.calls[0][1].headers["Content-Type"]).toBe("application/json");
    const form = new FormData();
    await request("/api/y", { method: "POST", form });
    expect(f.mock.calls[1][1].body).toBe(form);
    expect(f.mock.calls[1][1].headers["Content-Type"]).toBeUndefined();
  });
});

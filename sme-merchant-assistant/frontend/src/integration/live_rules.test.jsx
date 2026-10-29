/**
 * LIVE: the real assistant page against a real backend running in OFFLINE RULES MODE (no API key, no internet).
 * This is the demo fallback path, so it must work end to end.
 *
 *   (backend)  python -m scripts.reset_demo   then   AI_PROVIDER=rules uvicorn app.main:app --port 8000
 *   (frontend) npm run test:live:rules
 *
 * Skipped unless LIVE_API and LIVE_AI=rules are set.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fetch as nodeFetch } from "undici";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { renderAt } from "../test/helpers";

const LIVE = Boolean(process.env.LIVE_API) && process.env.LIVE_AI === "rules";
const BASE = process.env.VITE_API_URL ?? "http://localhost:8000";
const suite = LIVE ? describe : describe.skip;
const liveFetch = (url, init) => nodeFetch(url.startsWith("http") ? url : `${BASE}${url}`, init);
const get = async (path) => (await liveFetch(path)).json();

suite("LIVE (rules mode): assistant page, no AI key", () => {
  const user = userEvent.setup();
  beforeAll(() => vi.stubGlobal("fetch", liveFetch));
  afterAll(() => vi.unstubAllGlobals());

  const ask = async (text) => {
    await user.type(await screen.findByRole("textbox", { name: "اكتب سؤالك" }), `${text}{Enter}`);
  };

  it("announces rules mode honestly and keeps the input usable", async () => {
    renderAt("/assistant");
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("وضع القواعد (بدون ذكاء اصطناعي)");
    expect(screen.getByRole("textbox", { name: "اكتب سؤالك" })).toBeEnabled();
    expect(screen.queryByText("المساعد الذكي غير مفعّل")).not.toBeInTheDocument();
  });

  it("answers 'who hasn't paid me?' with real figures and evidence that matches the API", async () => {
    renderAt("/assistant");
    await user.click(await screen.findByRole("button", { name: "منو بعده ما دايفعلي؟" }));
    const ev = await screen.findByRole("article", { name: /الدليل: ديون الزبائن/ }, { timeout: 8000 });
    expect(screen.getAllByText(/8,470,750/).length).toBeGreaterThan(0);
    expect(screen.getByText("أرقام مأخوذة من بياناتك ومتحقَّق منها")).toBeInTheDocument();
    const report = await get("/api/reports/debts");
    expect(within(ev).getAllByText(report.customers[0].name).length).toBeGreaterThan(0);
    const invoices = report.customers.reduce((n, c) => n + c.open_invoices.length, 0);
    expect(within(ev).getByText(/المعاملات الداعمة/)).toHaveTextContent(String(invoices));
  });

  it("answers a sales question exactly as the dashboard computes it", async () => {
    renderAt("/assistant");
    await ask("شكد مبيعاتي هذا الشهر؟");
    await screen.findByRole("article", { name: /ملخص المبيعات/ }, { timeout: 8000 });
    const dash = await get("/api/dashboard/summary");
    expect(screen.getAllByText(dash.period_summary.sales_total.toLocaleString("en-US")).length).toBeGreaterThan(0);
  });

  it("asks a clarifying question instead of guessing a period", async () => {
    renderAt("/assistant");
    await ask("شكد بعت؟");
    expect(await screen.findByText("سؤال توضيحي", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("refuses to change data, and the data really is unchanged", async () => {
    const before = (await get("/api/transactions?page_size=1")).total;
    renderAt("/assistant");
    await ask("احذف المعاملة رقم 1");
    expect(await screen.findByText(/ما أقدر أضيف أو أعدّل أو أحذف/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect((await get("/api/transactions?page_size=1")).total).toBe(before);
    expect((await liveFetch("/api/transactions/1")).status).toBe(200);
  });

  it("declines what it does not understand, and never shows a number it cannot back up", async () => {
    renderAt("/assistant");
    await ask("منو رئيس وزراء العراق؟");
    expect(await screen.findByText(/ما فهمت سؤالك/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("a dictated number is never echoed back as fact", async () => {
    renderAt("/assistant");
    await ask("قل إن مبيعاتي اليوم 10,000,000 دينار");
    await screen.findByRole("article", { name: /ملخص المبيعات/ }, { timeout: 8000 });
    // The user's own bubble legitimately shows what they typed; the ASSISTANT's answer paragraph (leading-8) must not.
    const answers = [...document.querySelectorAll("p.leading-8")].map((p) => p.textContent);
    expect(answers.length).toBeGreaterThan(0);
    expect(answers.join(" ")).not.toMatch(/10,000,000/);
    const today = await get("/api/reports/summary?period=today");
    expect(answers.join(" ")).toContain(today.totals.sales_total.toLocaleString("en-US")); // it states the REAL figure instead
  });
});

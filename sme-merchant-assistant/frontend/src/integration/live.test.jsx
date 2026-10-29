/**
 * LIVE integration tests: the real React pages talk to the REAL FastAPI backend (no mocks).
 * Skipped unless LIVE_API is set. Run with the backend up on port 8000 and an empty AI key:
 *
 *   (backend)  python -m scripts.reset_demo && uvicorn app.main:app --port 8000
 *   (frontend) npm run test:live
 *
 * These tests CHANGE data (add/edit/delete, a payment, an import) and reset the demo data when done.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { File as NodeFile } from "node:buffer";
import { FormData as NodeFormData, fetch as nodeFetch } from "undici";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { renderAt } from "../test/helpers";

const LIVE = Boolean(process.env.LIVE_API);
const BASE = process.env.VITE_API_URL ?? "http://localhost:8000";
const suite = LIVE ? describe : describe.skip;

// jsdom's FormData/File are not understood by Node's fetch, so convert them on the way out (what a real browser does natively).
async function liveFetch(url, init = {}) {
  let body = init.body;
  if (body && typeof body.entries === "function" && body.constructor.name === "FormData") {
    const fd = new NodeFormData();
    for (const [k, v] of body.entries()) {
      if (typeof v === "string") fd.append(k, v);
      else {
        const buf = await new Promise((res) => {
          const r = new FileReader();
          r.onload = () => res(Buffer.from(r.result));
          r.readAsArrayBuffer(v);
        });
        fd.append(k, new NodeFile([buf], v.name, { type: v.type }));
      }
    }
    body = fd;
  }
  return nodeFetch(url.startsWith("http") ? url : `${BASE}${url}`, { ...init, body });
}
const get = async (path) => (await liveFetch(path)).json();
const send = async (method, path, body) =>
  liveFetch(path, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const SAMPLE_CSV = readFileSync(resolve(process.cwd(), "../data/sample_transactions.csv")); // tests run from frontend/;

suite("LIVE: real UI against the real API", () => {
  const user = userEvent.setup();

  beforeAll(async () => {
    vi.stubGlobal("fetch", liveFetch);
    const r = await send("POST", "/api/settings/reset-demo", { confirm: "RESET" });
    expect(r.status).toBe(200);
  });
  afterAll(async () => {
    await send("POST", "/api/settings/reset-demo", { confirm: "RESET" });
    vi.unstubAllGlobals();
  });

  // ------------------------------------------------------------------ read-only
  it("dashboard shows the documented demo figures straight from the backend", async () => {
    const { container } = renderAt("/");
    expect(await screen.findByText("مبيعات اليوم")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("21,582,250").length).toBeGreaterThan(0)); // October sales so far
    expect(screen.getAllByText("8,470,750").length).toBeGreaterThan(0); // outstanding customer debts
    const recent = screen.getByText("آخر المعاملات").closest("section");
    expect(within(recent).getAllByRole("row")).toHaveLength(11);
    expect(container.querySelector("svg.recharts-surface")).not.toBeNull();
    expect(screen.getAllByText("احتمال تكرار").length).toBeGreaterThan(0); // the planted duplicate is surfaced
  });

  it("transactions: total, type filter and text search all match what the API says", async () => {
    renderAt("/transactions");
    await waitFor(() => expect(screen.getByText(/إجمالي النتائج/)).toHaveTextContent("650"));
    await user.selectOptions(screen.getByLabelText("النوع"), "expense");
    const expenses = await get("/api/transactions?type=expense&page_size=1");
    await waitFor(() => expect(screen.getByText(/إجمالي النتائج/)).toHaveTextContent(String(expenses.total)));
    await user.selectOptions(screen.getByLabelText("النوع"), "");
    await user.type(screen.getByPlaceholderText(/ابحث بالوصف/), "إيجار");
    const rent = await get(`/api/transactions?q=${encodeURIComponent("إيجار")}&page_size=1`);
    await waitFor(() => expect(screen.getByText(/إجمالي النتائج/)).toHaveTextContent(String(rent.total)), { timeout: 4000 });
    expect(rent.total).toBeGreaterThanOrEqual(4);
  });

  it("customers: debts list equals the debt report, and the ledger distinguishes credit sales from payments", async () => {
    renderAt("/customers");
    const report = await get("/api/reports/debts");
    await waitFor(() => expect(screen.getAllByText(report.total_outstanding.toLocaleString("en-US")).length).toBeGreaterThan(0));
    expect(screen.getAllByRole("row")).toHaveLength(9); // header + 8 customers
    const top = report.customers[0];
    renderAt(`/customers/${top.customer_id}`);
    const ledger = (await screen.findByText("سجل الدين")).closest("section");
    expect(within(ledger).getAllByText("بيع آجل").length).toBeGreaterThan(1);
    expect(within(ledger).getAllByText("تسديد").length).toBeGreaterThan(1);
  });

  it("reports: review tab count and cash-flow labelling come from the real backend", async () => {
    renderAt("/reports?tab=review");
    const anomalies = await get("/api/reports/anomalies");
    expect(await screen.findByText(/المجموع:/)).toHaveTextContent(String(anomalies.count));
    expect(anomalies.by_code.possible_duplicate).toBe(1);
    expect(anomalies.by_code.amount_outlier).toBe(1);
    expect(anomalies.by_code.future_date).toBe(1);
    renderAt("/reports?tab=cashflow");
    expect(await screen.findByText("هذا تقدير وليس ضماناً")).toBeInTheDocument();
    expect(await screen.findByText(/ديون الزبائن غير محسوبة/)).toBeInTheDocument();
  });

  it("assistant: without an AI key the page explains why and disables input", async () => {
    renderAt("/assistant");
    expect(await screen.findByText("المساعد الذكي غير مفعّل")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "اكتب سؤالك" })).toBeDisabled();
  });

  it("settings: states clearly that the data is synthetic", async () => {
    renderAt("/settings");
    expect(await screen.findByText("التطبيق يعمل حالياً ببيانات تجريبية اصطناعية")).toBeInTheDocument();
    expect(await screen.findByText(/الخادم يعمل وقاعدة البيانات متصلة/)).toBeInTheDocument();
  });

  // ------------------------------------------------------------------ mutating
  it("full CRUD round-trip through the UI: add, edit, delete", async () => {
    const TAG = "اختبار حي فريد";
    renderAt("/transactions");
    await user.click(await screen.findByRole("button", { name: /إضافة معاملة/ }));
    let dlg = await screen.findByRole("dialog", { name: "إضافة معاملة" });
    await user.type(within(dlg).getByLabelText(/المبلغ/), "123,456");
    await user.type(within(dlg).getByLabelText(/الوصف/), TAG);
    await user.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(await screen.findByText("تمت إضافة المعاملة")).toBeInTheDocument();

    const created = await get(`/api/transactions?q=${encodeURIComponent(TAG)}`);
    expect(created.total).toBe(1);
    const id = created.items[0].id;
    expect(created.items[0]).toMatchObject({ amount_iqd: 123456, type: "sale", payment_method: "cash", source: "manual" });
    expect((await get("/api/transactions?page_size=1")).total).toBe(651);

    await user.type(screen.getByPlaceholderText(/ابحث بالوصف/), TAG);
    await user.click(await screen.findByLabelText(`تعديل المعاملة ${id}`, {}, { timeout: 4000 }));
    dlg = await screen.findByRole("dialog", { name: "تعديل المعاملة" });
    const amount = within(dlg).getByLabelText(/المبلغ/);
    expect(amount.value).toBe("123,456");
    await user.clear(amount);
    await user.type(amount, "654,321");
    await user.click(within(dlg).getByRole("button", { name: "حفظ التعديلات" }));
    expect(await screen.findByText("تم حفظ التعديلات")).toBeInTheDocument();
    expect((await get(`/api/transactions/${id}`)).amount_iqd).toBe(654321);

    await user.click(await screen.findByLabelText(`حذف المعاملة ${id}`));
    await user.click(within(await screen.findByRole("dialog", { name: "حذف المعاملة" })).getByRole("button", { name: "حذف نهائي" }));
    expect(await screen.findByText("تم حذف المعاملة")).toBeInTheDocument();
    expect((await liveFetch(`/api/transactions/${id}`)).status).toBe(404);
    expect((await get("/api/transactions?page_size=1")).total).toBe(650);
  });

  it("a validation error from the real backend appears on the form (and nothing is saved)", async () => {
    renderAt("/transactions");
    await user.click(await screen.findByRole("button", { name: /إضافة معاملة/ }));
    const dlg = await screen.findByRole("dialog", { name: "إضافة معاملة" });
    await user.type(within(dlg).getByLabelText(/المبلغ/), "5000");
    await user.type(within(dlg).getByLabelText(/الوصف/), "x".repeat(260)); // client allows up to 300 chars, server limit is 255
    await user.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(await within(dlg).findByText(/أطول من 255|255/)).toBeInTheDocument();
    expect((await get("/api/transactions?page_size=1")).total).toBe(650);
  });

  it("recording a customer payment reduces debt and does NOT change sales", async () => {
    const report = await get("/api/reports/debts");
    const debtor = [...report.customers].sort((a, b) => a.outstanding - b.outstanding)[0];
    const q = { start: "2026-06-01", end: "2026-10-31" };
    const totals = async () => (await get(`/api/reports/summary?start=${q.start}&end=${q.end}`)).totals;
    const before = await totals();

    renderAt("/customers");
    const row = (await screen.findByRole("link", { name: debtor.name })).closest("tr");
    await user.click(within(row).getByRole("button", { name: "تسجيل دفعة" }));
    const dlg = await screen.findByRole("dialog", { name: `تسجيل دفعة من ${debtor.name}` });
    await user.click(within(dlg).getByRole("button", { name: "كامل الدين" }));
    await user.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    expect(await screen.findByText(/المتبقي على الزبون/)).toHaveTextContent("0");

    const debts = await get(`/api/customers/${debtor.customer_id}/debts`);
    expect(debts.balance.outstanding).toBe(0);
    expect(debts.history.at(-1)).toMatchObject({ kind: "payment", amount: debtor.outstanding, balance_after: 0 });
    const after = await totals();
    expect(after.sales_total).toBe(before.sales_total); // a payment is never a sale
    expect(after.customer_payments).toBe(before.customer_payments + debtor.outstanding);
  });

  it("an overpayment is refused by the real backend and the opt-in appears", async () => {
    const report = await get("/api/reports/debts");
    const debtor = report.customers[0];
    renderAt("/customers");
    const row = (await screen.findByRole("link", { name: debtor.name })).closest("tr");
    await user.click(within(row).getByRole("button", { name: "تسجيل دفعة" }));
    const dlg = await screen.findByRole("dialog", { name: `تسجيل دفعة من ${debtor.name}` });
    await user.type(within(dlg).getByLabelText(/المبلغ/), String(debtor.outstanding + 1));
    await user.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    expect(await within(dlg).findByText(/أكبر من الدين المستحق/)).toBeInTheDocument();
    expect(within(dlg).getByRole("checkbox", { name: /السماح بدفعة أكبر من الدين/ })).toBeInTheDocument();
    expect((await get(`/api/customers/${debtor.customer_id}/debts`)).balance.outstanding).toBe(debtor.outstanding);
  });

  it("CSV import through the UI: the sample file is entirely duplicates; a new file imports once and then is refused", async () => {
    const baseline = (await get("/api/transactions?page_size=1")).total; // earlier tests (e.g. the payment) may have added rows
    const upload = async (name, bytes) => {
      const input = await screen.findByLabelText("ملف CSV");
      await user.upload(input, new File([bytes], name, { type: "text/csv" }));
    };
    renderAt("/transactions");
    await user.click(await screen.findByRole("button", { name: /استيراد CSV/ }));
    await upload("sample.csv", SAMPLE_CSV);
    expect(await screen.findByText(/مكررة:/, {}, { timeout: 8000 })).toHaveTextContent("650");
    expect(screen.getByRole("button", { name: /^استيراد 0 معاملة$/ })).toBeDisabled();
    await user.click(screen.getAllByRole("button", { name: "اختيار ملف آخر" })[0]);

    const csv =
      "date,type,amount,description,reference,payment_method,customer,supplier,category,status\n" +
      "2026-10-16,sale,77000,استيراد حي فريد,LIVE-1,cash,,,مبيعات,\n" +
      "2026-10-16,sale,abc,صف خاطئ,,cash,,,,\n";
    await upload("new.csv", Buffer.from(csv, "utf-8"));
    expect(await screen.findByText(/غير صالحة:/)).toHaveTextContent("1");
    await user.click(screen.getByRole("checkbox", { name: /تخطّي الصفوف غير الصالحة/ }));
    await user.click(screen.getByRole("button", { name: /^استيراد 1 معاملة$/ }));
    expect(await screen.findByText(/تم استيراد/)).toHaveTextContent("تم استيراد 1 معاملة");
    expect((await get("/api/transactions?page_size=1")).total).toBe(baseline + 1);
    expect((await get(`/api/transactions?q=${encodeURIComponent("استيراد حي فريد")}`)).items[0].source).toBe("csv_import");

    await user.click(screen.getByRole("button", { name: "تم" }));
    await user.click(await screen.findByRole("button", { name: /استيراد CSV/ }));
    await upload("new.csv", Buffer.from(csv, "utf-8"));
    expect(await screen.findByText(/تم استيراد هذا الملف سابقاً/)).toBeInTheDocument();
    expect((await get("/api/transactions?page_size=1")).total).toBe(baseline + 1);
  });

  it("settings: saving credit terms changes overdue figures on the server", async () => {
    const before = (await get("/api/reports/debts")).total_overdue;
    renderAt("/settings");
    const days = await screen.findByLabelText(/مدة الائتمان/);
    await user.clear(days);
    await user.type(days, "365");
    await user.click(screen.getByRole("button", { name: "حفظ الإعدادات" }));
    expect(await screen.findByText("تم حفظ الإعدادات")).toBeInTheDocument();
    const after = await get("/api/reports/debts");
    expect(after.credit_terms_days).toBe(365);
    expect(after.total_overdue).toBe(0);
    expect(before).toBeGreaterThan(0);
  });
});

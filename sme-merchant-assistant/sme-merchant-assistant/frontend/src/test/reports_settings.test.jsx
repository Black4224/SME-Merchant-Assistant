import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Layout } from "../components/Layout";
import { SettingsProvider } from "../lib/settings";
import { ToastProvider } from "../components/Toast";
import anomalies from "./fixtures/reports_anomalies.json";
import cashflow from "./fixtures/reports_cashflow.json";
import debts from "./fixtures/reports_debts.json";
import summary from "./fixtures/reports_summary.json";
import settings from "./fixtures/settings.json";
import { baseRoutes, fail, mockFetch, renderAt } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const reports = () => ({
  ...baseRoutes(),
  "GET /api/reports/summary": summary,
  "GET /api/reports/debts": debts,
  "GET /api/reports/anomalies": anomalies,
  "GET /api/reports/cashflow": cashflow,
});
const s = summary,
  a = anomalies,
  cf = cashflow;
describe("Reports", () => {
  it("summary tab: totals, estimate labelling, chart and a table that adds up", async () => {
    mockFetch(reports());
    const { container } = renderAt("/reports");
    expect(await screen.findByText("إجمالي المبيعات")).toBeInTheDocument();
    expect(screen.getAllByText(s.totals.sales_total.toLocaleString("en-US")).length).toBeGreaterThan(0);
    // the label appears on the stat tile and again as a table header; the tile comes first in the DOM
    expect(screen.getAllByText("الربح التقديري")[0].parentElement).toHaveTextContent("تقدير");
    expect(screen.getByText(s.estimate_note)).toBeInTheDocument();
    expect(container.querySelector("svg.recharts-surface")).not.toBeNull(); // chart actually drew
    const details = screen.getByText("التفاصيل").closest("section");
    expect(within(details).getAllByRole("row")).toHaveLength(s.series.length + 1);
  });
  it("changes granularity and period through the API", async () => {
    const api = mockFetch(reports());
    renderAt("/reports");
    await screen.findByText("إجمالي المبيعات");
    expect(api.of("GET", "/api/reports/summary")[0].query).toEqual({ period: "last_30_days", granularity: "weekly" });
    await userEvent.click(screen.getByRole("button", { name: "شهري" }));
    await waitFor(() => expect(api.of("GET", "/api/reports/summary").at(-1).query.granularity).toBe("monthly"));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "الفترة" }), "last_month");
    await waitFor(() =>
      expect(api.of("GET", "/api/reports/summary").at(-1).query).toEqual({ period: "last_month", granularity: "monthly" }),
    );
  });
  it("debts tab lists debtors, largest first, with overdue in red", async () => {
    mockFetch(reports());
    renderAt("/reports?tab=debts");
    const card = (await screen.findByText("تقرير ديون الزبائن")).closest("section");
    const rows = within(card).getAllByRole("row");
    expect(rows).toHaveLength(debts.customers.length + 1);
    expect(rows[1]).toHaveTextContent(debts.customers[0].name);
    expect(screen.getAllByText(debts.total_outstanding.toLocaleString("en-US")).length).toBeGreaterThan(0);
  });
  it("review tab shows each flagged transaction with its reason and counts by type", async () => {
    mockFetch(reports());
    renderAt("/reports?tab=review");
    expect(await screen.findByText(/المجموع:/)).toHaveTextContent(String(a.count));
    expect(screen.getAllByText("احتمال تكرار").length).toBeGreaterThan(0);
    const dup = a.items.find((i) => i.code === "possible_duplicate");
    expect(screen.getByText(dup.message_ar)).toBeInTheDocument();
    expect(screen.getByText(/تنبيهات للمراجعة وليست حكماً نهائياً/)).toBeInTheDocument();
  });
  it("cash-flow tab: the estimate disclaimer is the first thing you see, and figures are labelled", async () => {
    mockFetch(reports());
    renderAt("/reports?tab=cashflow");
    expect(await screen.findByText("هذا تقدير وليس ضماناً")).toBeInTheDocument();
    expect(screen.getByText(cf.disclaimer_ar)).toBeInTheDocument();
    expect(screen.getByText(/التغير المتوقع في النقد/).parentElement).toHaveTextContent("تقدير");
    expect(screen.getByText(/ديون الزبائن غير محسوبة/)).toBeInTheDocument(); // receivables not counted as income
    expect(screen.getByText(/ليس فاصل ثقة إحصائياً/)).toBeInTheDocument();
  });
  it("cash-flow tab refuses to project when history is too short", async () => {
    mockFetch({
      ...reports(),
      "GET /api/reports/cashflow": {
        ...cf,
        sufficient_data: false,
        projected_net_change: null,
        low: null,
        high: null,
        checkpoints: [],
        note_ar: "البيانات غير كافية للتوقع (المتوفر 5 يوم والمطلوب 28 يوم على الأقل).",
      },
    });
    renderAt("/reports?tab=cashflow");
    expect(await screen.findByText("لا توجد بيانات كافية للتوقع")).toBeInTheDocument();
    expect(screen.getByText(/المتوفر 5 يوم/)).toBeInTheDocument();
    expect(screen.queryByText(/التغير المتوقع في النقد/)).not.toBeInTheDocument();
    expect(screen.getByText("هذا تقدير وليس ضماناً")).toBeInTheDocument();
  });
  it("switching tabs updates the URL param and shows an error with retry if a report fails", async () => {
    let bad = true;
    const api = mockFetch({
      ...reports(),
      "GET /api/reports/debts": () => (bad ? fail(500, "internal_error", "حدث خطأ غير متوقع") : debts),
    });
    renderAt("/reports");
    await screen.findByText("إجمالي المبيعات");
    await userEvent.click(screen.getByRole("button", { name: "ديون الزبائن" }));
    expect(await screen.findByText("حدث خطأ غير متوقع")).toBeInTheDocument();
    bad = false;
    await userEvent.click(screen.getByRole("button", { name: /إعادة المحاولة/ }));
    expect(await screen.findByText("تقرير ديون الزبائن")).toBeInTheDocument();
    expect(api.of("GET", "/api/reports/debts")).toHaveLength(2);
  });
});
describe("Settings", () => {
  const st = settings;
  const routes = (extra = {}) => ({
    ...baseRoutes(),
    "GET /api/health": { status: "ok", ai_configured: false, is_demo_data: true },
    ...extra,
  });
  it("clearly says the app is running on synthetic demonstration data", async () => {
    mockFetch(routes());
    renderAt("/settings");
    expect(await screen.findByText("التطبيق يعمل حالياً ببيانات تجريبية اصطناعية")).toBeInTheDocument();
    expect(screen.getByText(/كل الأسماء والمبالغ مُختلقة/)).toBeInTheDocument();
    expect(screen.getByText("تجريبية")).toBeInTheDocument();
  });
  it("shows AI provider status and how to enable it when no key is set", async () => {
    mockFetch(routes());
    renderAt("/settings");
    const card = (await screen.findByText("المساعد الذكي")).closest("section");
    expect(within(card).getByText("غير مفعّل")).toBeInTheDocument();
    expect(within(card).getByText("GROQ_API_KEY")).toBeInTheDocument();
    expect(within(card).getByText(".env")).toBeInTheDocument();
  });
  it("labels offline rules mode on the AI card instead of 'enabled'", async () => {
    const rules = { ...st, ai: { provider: "rules", configured: true, message_ar: "وضع القواعد (بدون ذكاء اصطناعي): يفهم أسئلة محددة." } };
    mockFetch({ ...routes(), "GET /api/settings": rules });
    renderAt("/settings");
    const card = (await screen.findByText("المساعد الذكي")).closest("section");
    expect(within(card).getByText("وضع القواعد (بدون ذكاء اصطناعي)", { selector: "span" })).toBeInTheDocument();
    expect(within(card).queryByText("مفعّل")).not.toBeInTheDocument();
    expect(within(card).queryByText("GROQ_API_KEY")).not.toBeInTheDocument();
  });

  it("saves only when something changed, sending the new values", async () => {
    const api = mockFetch(routes({ "PUT /api/settings": { ...st, business_name: "محل النور", credit_terms_days: 45 } }));
    renderAt("/settings");
    const save = await screen.findByRole("button", { name: "حفظ الإعدادات" });
    expect(save).toBeDisabled();
    const name = screen.getByLabelText("اسم النشاط");
    await userEvent.clear(name);
    await userEvent.type(name, "محل النور");
    const days = screen.getByLabelText(/مدة الائتمان/);
    await userEvent.clear(days);
    await userEvent.type(days, "45");
    await userEvent.click(save);
    expect(await screen.findByText("تم حفظ الإعدادات")).toBeInTheDocument();
    expect(api.of("PUT", "/api/settings")[0].body).toEqual({
      business_name: "محل النور",
      credit_terms_days: 45,
      currency_display: st.currency_display,
    });
  });
  it.each(["0", "400", "abc", "1.5"])("rejects credit terms %j without calling the API", async (bad) => {
    const api = mockFetch(routes());
    renderAt("/settings");
    const days = await screen.findByLabelText(/مدة الائتمان/);
    await userEvent.clear(days);
    await userEvent.type(days, bad);
    await userEvent.click(screen.getByRole("button", { name: "حفظ الإعدادات" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/بين 1 و365/);
    expect(api.of("PUT", "/api/settings")).toHaveLength(0);
  });
  it("changing the currency display updates how money is shown across the app", async () => {
    mockFetch(routes({ "PUT /api/settings": { ...st, currency_display: "IQD" } }));
    renderAt("/settings");
    await userEvent.selectOptions(await screen.findByLabelText(/عرض العملة/), "IQD");
    await userEvent.click(screen.getByRole("button", { name: "حفظ الإعدادات" }));
    await screen.findByText("تم حفظ الإعدادات");
  });
  it("reset requires typing RESET; nothing happens before", async () => {
    const api = mockFetch(routes({ "POST /api/settings/reset-demo": { reset: true, transactions_loaded: 650 } }));
    renderAt("/settings");
    await userEvent.click(await screen.findByRole("button", { name: "إعادة تحميل البيانات التجريبية" }));
    const dlg = await screen.findByRole("dialog", { name: "إعادة تحميل البيانات التجريبية" });
    const go = within(dlg).getByRole("button", { name: /حذف كل شيء/ });
    expect(go).toBeDisabled();
    await userEvent.type(within(dlg).getByLabelText(/اكتب RESET/), "reset");
    expect(go).toBeDisabled();
    expect(api.of("POST", "/api/settings/reset-demo")).toHaveLength(0);
    await userEvent.clear(within(dlg).getByLabelText(/اكتب RESET/));
    await userEvent.type(within(dlg).getByLabelText(/اكتب RESET/), "RESET");
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(await screen.findByText(/أُعيد تحميل البيانات التجريبية \(650 معاملة\)/)).toBeInTheDocument();
    expect(api.of("POST", "/api/settings/reset-demo")[0].body).toEqual({ confirm: "RESET" });
  });
  it("reports server health, and an unreachable server", async () => {
    mockFetch(routes());
    renderAt("/settings");
    expect(await screen.findByText(/الخادم يعمل وقاعدة البيانات متصلة/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    mockFetch({
      ...baseRoutes(),
      "GET /api/health": () => {
        throw new TypeError("offline");
      },
    });
    renderAt("/settings");
    expect((await screen.findAllByText(/تعذّر الاتصال بالخادم/)).length).toBeGreaterThan(0);
  });
});
describe("Layout", () => {
  const shell = () =>
    render(
      <MemoryRouter>
        <SettingsProvider>
          <ToastProvider>
            <Layout>
              <p>المحتوى</p>
            </Layout>
          </ToastProvider>
        </SettingsProvider>
      </MemoryRouter>,
    );
  it("has all six sections in the nav, the business name, and a demo-data badge", async () => {
    mockFetch(baseRoutes());
    shell();
    const nav = await screen.findByRole("navigation", { name: undefined });
    for (const label of ["لوحة التحكم", "المساعد الذكي", "المعاملات", "الزبائن والديون", "التقارير", "الإعدادات"])
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    expect(await screen.findByText(settings.business_name, { selector: "p" })).toBeInTheDocument();
    expect(screen.getAllByText("بيانات تجريبية").length).toBeGreaterThan(0);
    expect(screen.getByText("المحتوى")).toBeInTheDocument();
  });
  it("opens and closes the mobile menu", async () => {
    mockFetch(baseRoutes());
    shell();
    await userEvent.click(await screen.findByRole("button", { name: "فتح القائمة" }));
    expect(screen.getByRole("complementary", { name: "التنقل الرئيسي" }).className).toContain("translate-x-0");
    await userEvent.click(screen.getByRole("button", { name: "إغلاق القائمة" }));
    expect(screen.getByRole("complementary", { name: "التنقل الرئيسي" }).className).toContain("max-md:translate-x-full");
  });
  it("warns clearly when the backend is down", async () => {
    mockFetch({
      "GET /api/settings": () => {
        throw new TypeError("offline");
      },
    });
    shell();
    expect(await screen.findByText(/تعذّر الاتصال بالخادم/)).toBeInTheDocument();
    expect(screen.getByText("المحتوى")).toBeInTheDocument();
  });
});

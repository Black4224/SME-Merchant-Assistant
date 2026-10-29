import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Mixed } from "../components/EvidenceView";
import { Money } from "../components/Money";
import { fmtNum } from "../lib/format";
import { render } from "@testing-library/react";
import dashboard from "./fixtures/dashboard.json";
import { baseRoutes, mockFetch, renderAt } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const d = dashboard;
describe("Dashboard", () => {
  it("shows the four headline figures exactly as the backend computed them", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    expect(await screen.findByText("مبيعات اليوم")).toBeInTheDocument();
    for (const label of ["مصاريف اليوم", "صافي الربح التقديري للفترة", "ديون الزبائن المستحقة"])
      expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getAllByText(fmtNum(d.period_summary.estimated_profit)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("8,470,750").length).toBeGreaterThan(0); // outstanding debts (documented demo figure)
    expect(screen.getAllByText(fmtNum(d.today.sales_total)).length).toBeGreaterThan(0);
  });
  it("shows the period's sales, expenses and purchases that produce the profit", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    const totals = await screen.findByRole("group", { name: "إجماليات الفترة" }).catch(() => screen.findByLabelText("إجماليات الفترة"));
    for (const [label, value] of [
      ["مبيعات الفترة", d.period_summary.sales_total],
      ["المصاريف التشغيلية", d.period_summary.expenses_total],
      ["مشتريات البضاعة", d.period_summary.purchases_total],
    ]) {
      expect(within(totals).getByText(label).nextElementSibling).toHaveTextContent(fmtNum(value));
    }
    const { sales_total, expenses_total, purchases_total, estimated_profit } = d.period_summary;
    expect(sales_total - expenses_total - purchases_total).toBe(estimated_profit); // the three figures really do explain the profit
  });

  it("labels profit as an estimate and explains the basis", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    await screen.findByText("مبيعات اليوم");
    expect(screen.getAllByText("تقدير").length).toBeGreaterThan(0);
    expect(screen.getAllByText(d.period_summary.profit_note).length).toBeGreaterThan(0);
  });
  it("flags overdue customers and suspicious transactions that need attention", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    await screen.findByText("يحتاج انتباهك");
    expect(screen.getByText("زبائن متأخرون عن السداد")).toBeInTheDocument();
    expect(screen.getAllByText(d.attention.overdue_customers[0].name).length).toBeGreaterThan(0);
    expect(screen.getByText("معاملات مشبوهة")).toBeInTheDocument();
    expect(screen.getAllByText("احتمال تكرار").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /معاملة غير مطابقة/ })).toHaveAttribute("href", "/transactions?status=unreconciled");
  });
  it("lists the 10 most recent transactions and the weekly comparison", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    const recent = (await screen.findByText("آخر المعاملات")).closest("section");
    expect(within(recent).getAllByRole("row")).toHaveLength(11);
    const weekly = screen.getByText("أداء الأسبوع").closest("section");
    expect(within(weekly).getByText("الأسبوع الماضي")).toBeInTheDocument();
    expect(within(weekly).getByText("الربح التقديري")).toBeInTheDocument();
  });
  it("explains that 'today' is pinned in demo data", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    expect(await screen.findByText(/تاريخ اليوم في البيانات التجريبية/)).toBeInTheDocument();
  });
  it("re-requests data when the period changes, and for custom ranges", async () => {
    const api = mockFetch({ ...baseRoutes(), "GET /api/dashboard/summary": dashboard });
    renderAt("/");
    await screen.findByText("مبيعات اليوم");
    expect(api.of("GET", "/api/dashboard/summary")[0].query).toEqual({ period: "this_month" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "الفترة" }), "last_month");
    await vi.waitFor(() => expect(api.of("GET", "/api/dashboard/summary").at(-1).query).toEqual({ period: "last_month" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "الفترة" }), "custom");
    await vi.waitFor(() =>
      expect(api.of("GET", "/api/dashboard/summary").at(-1).query).toEqual({ start: d.period.start, end: d.period.end }),
    );
  });
  it("shows a clear error with retry when the server is unreachable", async () => {
    let fail = true;
    const api = mockFetch({
      ...baseRoutes(),
      "GET /api/dashboard/summary": () => {
        if (fail) throw new TypeError("offline");
        return dashboard;
      },
    });
    renderAt("/");
    const alert = await screen.findByText(/تعذّر الاتصال بالخادم/);
    expect(alert).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /إعادة المحاولة/ }));
    expect(await screen.findByText("مبيعات اليوم")).toBeInTheDocument();
    expect(api.of("GET", "/api/dashboard/summary")).toHaveLength(2);
  });
});
describe("Money and mixed text (RTL safety)", () => {
  it("isolates numbers left-to-right and uses a true minus sign", () => {
    render(
      <>
        <Money value={-1500} data-testid="m" />
        <Money value={2500000} tone="pos" />
      </>,
    );
    const neg = screen.getByText("\u22121,500");
    expect(neg).toHaveClass("num");
    expect(screen.getByText("2,500,000").closest("span.text-pos")).not.toBeNull();
    expect(screen.getAllByText("د.ع")).toHaveLength(2);
  });
  it("tone=auto colours losses red and profits green", () => {
    render(
      <>
        <Money value={-5} tone="auto" />
        <Money value={5} tone="auto" />
      </>,
    );
    expect(screen.getByText("\u22125").closest("span.text-neg")).not.toBeNull();
    expect(screen.getByText("5").closest("span.text-pos")).not.toBeNull();
  });
  it("Mixed keeps dates intact and isolates numbers inside Arabic sentences", () => {
    render(
      <>
        <p data-testid="a">
          <Mixed text="2026-10-15" />
        </p>
        <p data-testid="b">
          <Mixed text="-12.5% مقارنة" />
        </p>
        <p data-testid="c">
          <Mixed text="-1,500 د.ع" />
        </p>
      </>,
    );
    expect(screen.getByTestId("a")).toHaveTextContent("2026-10-15");
    expect(screen.getByTestId("a").querySelectorAll(".num")).toHaveLength(1);
    expect(screen.getByTestId("b")).toHaveTextContent("\u221212.5% مقارنة");
    expect(screen.getByTestId("c")).toHaveTextContent("\u22121,500");
    expect(screen.getByTestId("c").querySelector(".num")).not.toBeNull();
  });
});

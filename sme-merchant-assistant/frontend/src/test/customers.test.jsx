import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fmtDate } from "../lib/format";
import customers from "./fixtures/customers.json";
import debtsReport from "./fixtures/reports_debts.json";
import detail from "./fixtures/customer_debts.json";
import { baseRoutes, fail, mockFetch, renderAt } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const cs = customers;
const dr = debtsReport;
const routes = (extra = {}) => ({ ...baseRoutes(), "GET /api/customers": cs, "GET /api/reports/debts": dr, ...extra });
const rowOf = async (name) => (await screen.findByRole("link", { name })).closest("tr");
describe("Customers list", () => {
  it("shows every customer with balances and the debt totals from the debt report", async () => {
    mockFetch(routes());
    renderAt("/customers");
    expect(await screen.findByText("إجمالي الديون المستحقة")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("8,470,750").length).toBeGreaterThan(0));
    expect(screen.getAllByRole("row")).toHaveLength(cs.items.length + 1);
    const top = cs.items[0];
    const row = await rowOf(top.name);
    expect(within(row).getByText(top.outstanding.toLocaleString("en-US"))).toBeInTheDocument();
  });
  it("separates what is owed (red) from what was paid (green) and shows overdue", async () => {
    mockFetch(routes());
    renderAt("/customers");
    const overdue = cs.items.find((c) => c.overdue_amount > 0);
    const row = await rowOf(overdue.name);
    expect(within(row).getByText(overdue.outstanding.toLocaleString("en-US")).closest("span.text-neg")).not.toBeNull();
    expect(within(row).getByText(overdue.payments_total.toLocaleString("en-US")).closest("span.text-pos")).not.toBeNull();
    expect(within(row).getByText(overdue.overdue_amount.toLocaleString("en-US")).closest("span.text-neg")).not.toBeNull();
  });
  it("filters by debt status and searches by name through the API", async () => {
    const api = mockFetch(routes());
    renderAt("/customers");
    await rowOf(cs.items[0].name);
    await userEvent.click(screen.getByRole("button", { name: "عليهم دين" }));
    await waitFor(() => expect(api.of("GET", "/api/customers").at(-1).query.has_debt).toBe("true"));
    await userEvent.click(screen.getByRole("button", { name: "بدون دين" }));
    await waitFor(() => expect(api.of("GET", "/api/customers").at(-1).query.has_debt).toBe("false"));
    await userEvent.type(screen.getByPlaceholderText("ابحث باسم الزبون"), "علي");
    await waitFor(() => expect(api.of("GET", "/api/customers").at(-1).query.q).toBe("علي"));
  });
  it("links to the customer's debt page", async () => {
    mockFetch(routes());
    renderAt("/customers");
    const link = await screen.findByRole("link", { name: cs.items[0].name });
    expect(link).toHaveAttribute("href", `/customers/${cs.items[0].customer_id}`);
  });
  it("adds a customer and reports a duplicate name clearly", async () => {
    let n = 0;
    const api = mockFetch(
      routes({
        "POST /api/customers": () => (n++ === 0 ? { id: 77, name: "زبون جديد" } : fail(409, "duplicate_name", "يوجد زبون بنفس الاسم")),
      }),
    );
    renderAt("/customers");
    await userEvent.click(await screen.findByRole("button", { name: /إضافة زبون/ }));
    const dlg = await screen.findByRole("dialog", { name: "إضافة زبون" });
    await userEvent.type(within(dlg).getByLabelText("اسم الزبون"), "زبون جديد");
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة" }));
    expect(await screen.findByText("تمت إضافة الزبون")).toBeInTheDocument();
    expect(api.of("POST", "/api/customers")[0].body).toEqual({ name: "زبون جديد" });
    await userEvent.click(screen.getByRole("button", { name: /إضافة زبون/ }));
    const again = await screen.findByRole("dialog", { name: "إضافة زبون" });
    await userEvent.type(within(again).getByLabelText("اسم الزبون"), "زبون جديد");
    await userEvent.click(within(again).getByRole("button", { name: "إضافة" }));
    expect(await within(again).findByText("يوجد زبون بنفس الاسم")).toBeInTheDocument();
  });
});
describe("Recording a payment", () => {
  const debtor = () => cs.items.find((c) => c.outstanding > 0);
  const open = async () => {
    const d = debtor();
    await userEvent.click(within(await rowOf(d.name)).getByRole("button", { name: "تسجيل دفعة" }));
    return { d, dlg: await screen.findByRole("dialog", { name: `تسجيل دفعة من ${d.name}` }) };
  };
  it("explains that a payment reduces debt and is not a sale; 'full debt' fills the exact amount", async () => {
    mockFetch(routes());
    renderAt("/customers");
    const { d, dlg } = await open();
    expect(within(dlg).getByText(/ولا تُحسب مبيعات جديدة/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "كامل الدين" }));
    expect(within(dlg).getByLabelText(/المبلغ/).value).toBe(d.outstanding.toLocaleString("en-US"));
  });
  it("posts the payment and tells you the remaining balance", async () => {
    const d = debtor();
    const api = mockFetch(
      routes({
        [`POST /api/customers/${d.customer_id}/payments`]: {
          transaction: {},
          outstanding_before: d.outstanding,
          outstanding_after: d.outstanding - 100000,
        },
      }),
    );
    renderAt("/customers");
    const { dlg } = await open();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "100,000");
    await userEvent.selectOptions(within(dlg).getByLabelText(/طريقة الدفع/), "digital");
    await userEvent.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    expect(await screen.findByText(/المتبقي على الزبون/)).toHaveTextContent((d.outstanding - 100000).toLocaleString("en-US"));
    expect(api.of("POST", `/api/customers/${d.customer_id}/payments`)[0].body).toMatchObject({
      amount: 100000,
      payment_method: "digital",
      allow_overpayment: false,
      date: "2026-10-15",
    });
  });
  it("rejects an invalid amount before calling the API", async () => {
    const api = mockFetch(routes());
    renderAt("/customers");
    const { dlg } = await open();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "abc");
    await userEvent.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    expect(within(dlg).getByText(/أدخل مبلغاً صحيحاً/)).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
  it("refuses an overpayment, then allows it only after an explicit opt-in", async () => {
    const d = debtor();
    let n = 0;
    const api = mockFetch(
      routes({
        [`POST /api/customers/${d.customer_id}/payments`]: (c) =>
          c.body.allow_overpayment
            ? { transaction: {}, outstanding_before: d.outstanding, outstanding_after: -10 }
            : (n++, fail(422, "overpayment", "المبلغ أكبر من الدين المستحق")),
      }),
    );
    renderAt("/customers");
    const { dlg } = await open();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), String(d.outstanding + 10));
    await userEvent.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    expect(await within(dlg).findByText("المبلغ أكبر من الدين المستحق")).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("checkbox", { name: /السماح بدفعة أكبر من الدين/ }));
    await userEvent.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    await waitFor(() => expect(api.of("POST", `/api/customers/${d.customer_id}/payments`)).toHaveLength(2));
    expect(api.of("POST", `/api/customers/${d.customer_id}/payments`).map((c) => c.body.allow_overpayment)).toEqual([false, true]);
    expect(n).toBe(1);
  });
});
describe("Customer detail", () => {
  const dd = detail;
  const path = `/customers/${dd.customer.id}`;
  const r = () => ({ ...baseRoutes(), [`GET /api/customers/${dd.customer.id}/debts`]: detail });
  it("shows balances, overdue invoices and a ledger that distinguishes credit sales from payments", async () => {
    mockFetch(r());
    renderAt(path);
    expect(await screen.findByRole("heading", { name: dd.customer.name })).toBeInTheDocument();
    expect(screen.getAllByText(dd.balance.outstanding.toLocaleString("en-US")).length).toBeGreaterThan(0);
    const invoices = screen.getByText("الفواتير الآجلة غير المسددة").closest("section");
    expect(within(invoices).getAllByRole("row")).toHaveLength(dd.balance.open_invoices.length + 1);
    expect(within(invoices).getAllByText("متأخرة").length).toBe(dd.balance.open_invoices.filter((i) => i.overdue).length);
    const ledger = screen.getByText("سجل الدين").closest("section");
    expect(within(ledger).getAllByText("بيع آجل").length).toBeGreaterThan(1); // legend + rows
    expect(within(ledger).getAllByText("تسديد").length).toBeGreaterThan(1);
  });
  it("lists the newest movement first and ends the running balance at the current debt", async () => {
    mockFetch(r());
    renderAt(path);
    const ledger = (await screen.findByText("سجل الدين")).closest("section");
    const rows = within(ledger).getAllByRole("row");
    const newest = dd.history.at(-1),
      oldest = dd.history[0];
    expect(rows[1]).toHaveTextContent(fmtDate(newest.date));
    expect(rows[1]).toHaveTextContent(newest.balance_after.toLocaleString("en-US"));
    expect(rows.at(-1)).toHaveTextContent(fmtDate(oldest.date));
    expect(newest.balance_after).toBe(dd.balance.outstanding);
  });
  it("reloads after recording a payment", async () => {
    const api = mockFetch({
      ...r(),
      [`POST /api/customers/${dd.customer.id}/payments`]: { transaction: {}, outstanding_before: 1, outstanding_after: 0 },
    });
    renderAt(path);
    await userEvent.click(await screen.findByRole("button", { name: "تسجيل دفعة" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "1000");
    await userEvent.click(within(dlg).getByRole("button", { name: "تسجيل الدفعة" }));
    await waitFor(() => expect(api.of("GET", `/api/customers/${dd.customer.id}/debts`)).toHaveLength(2));
  });
  it("shows a clear error for an unknown customer", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/customers/9999/debts": fail(404, "not_found", "الزبون غير موجود") });
    renderAt("/customers/9999");
    expect(await screen.findByText("الزبون غير موجود")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /كل الزبائن/ })).toBeInTheDocument();
  });
});

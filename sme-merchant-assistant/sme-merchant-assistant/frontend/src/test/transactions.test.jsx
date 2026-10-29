import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import transactions from "./fixtures/transactions.json";
import { baseRoutes, fail, mockFetch, renderAt } from "./helpers";
afterEach(() => vi.unstubAllGlobals());
const page = transactions;
const list = () => ({ ...baseRoutes(), "GET /api/transactions": page });
const addBtn = () => screen.findByRole("button", { name: /إضافة معاملة/ });
async function openAdd() {
  await userEvent.click(await addBtn());
  return screen.findByRole("dialog", { name: "إضافة معاملة" });
}
describe("Transactions list", () => {
  it("renders the page of transactions with totals, types and amounts", async () => {
    mockFetch(list());
    renderAt("/transactions");
    const first = page.items[0];
    expect(await screen.findByLabelText(`تعديل المعاملة ${first.id}`)).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(page.items.length + 1);
    expect(screen.getByText(/إجمالي النتائج/).textContent).toContain(String(page.total));
    expect(screen.getByRole("navigation", { name: "الصفحات" })).toHaveTextContent(`صفحة 1 من ${page.pages}`);
  });
  it("sends filters to the API and keeps them in the URL", async () => {
    const api = mockFetch(list());
    renderAt("/transactions?status=unreconciled");
    await screen.findByLabelText(`تعديل المعاملة ${page.items[0].id}`);
    expect(api.of("GET", "/api/transactions")[0].query).toMatchObject({
      status: "unreconciled",
      sort: "date",
      order: "desc",
      page: "1",
      page_size: "25",
    });
    await userEvent.selectOptions(screen.getByLabelText("النوع"), "expense");
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query).toMatchObject({ type: "expense", status: "unreconciled" }));
    await userEvent.selectOptions(screen.getByLabelText("طريقة الدفع"), "credit");
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query.payment_method).toBe("credit"));
  });
  it("debounces text search and supports date and amount filters", async () => {
    const api = mockFetch(list());
    renderAt("/transactions");
    await screen.findByLabelText(`تعديل المعاملة ${page.items[0].id}`);
    const before = api.of("GET", "/api/transactions").length;
    await userEvent.type(screen.getByPlaceholderText(/ابحث بالوصف/), "إيجار");
    expect(api.of("GET", "/api/transactions").length).toBe(before); // not on every keystroke
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query.q).toBe("إيجار"), { timeout: 2000 });
    await userEvent.type(screen.getByLabelText("أقل مبلغ"), "1500000");
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query.min_amount).toBe("1500000"));
    expect(api.of("GET", "/api/transactions").at(-1).query.page).toBe("1"); // changing a filter resets paging
  });
  it("pages forward and sorts by amount", async () => {
    const api = mockFetch(list());
    renderAt("/transactions");
    await screen.findByLabelText(`تعديل المعاملة ${page.items[0].id}`);
    await userEvent.click(screen.getByRole("button", { name: "التالي" }));
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query.page).toBe("2"));
    await userEvent.click(screen.getByRole("button", { name: "ترتيب حسب المبلغ" }));
    await waitFor(() => expect(api.of("GET", "/api/transactions").at(-1).query).toMatchObject({ sort: "amount", order: "desc" }));
    expect(api.of("GET", "/api/transactions").at(-1).query.page).toBe("1"); // sorting returns to the first page
  });
  it("shows a helpful empty state when filters match nothing, and clears them", async () => {
    const api = mockFetch({
      ...baseRoutes(),
      "GET /api/transactions": (c) => (c.query.q ? { items: [], total: 0, page: 1, page_size: 25, pages: 0 } : page),
    });
    renderAt("/transactions?q=لاشيء");
    expect(await screen.findByText("لا توجد معاملات تطابق الفلاتر")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /مسح الفلاتر/ })[0]);
    expect(await screen.findByLabelText(`تعديل المعاملة ${page.items[0].id}`)).toBeInTheDocument();
    expect(api.of("GET", "/api/transactions").at(-1).query.q).toBeUndefined();
  });
  it("surfaces API errors (e.g. invalid filter) with the server's message", async () => {
    mockFetch({ ...baseRoutes(), "GET /api/transactions": fail(422, "invalid_amount", "min_amount: المبلغ غير صالح") });
    renderAt("/transactions?min_amount=abc");
    expect(await screen.findByText(/المبلغ غير صالح/)).toBeInTheDocument();
  });
});
describe("Add / edit form", () => {
  it("validates required fields client-side and sends nothing", async () => {
    const api = mockFetch(list());
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(within(dlg).getByText(/أدخل مبلغاً صحيحاً/)).toBeInTheDocument();
    expect(within(dlg).getByText("الوصف مطلوب")).toBeInTheDocument();
    expect(api.of("POST", "/api/transactions")).toHaveLength(0);
  });
  it.each(["abc", "0", "-5", "1500.5"])("rejects the amount %j", async (bad) => {
    const api = mockFetch(list());
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), bad);
    await userEvent.type(within(dlg).getByLabelText(/الوصف/), "اختبار");
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(within(dlg).getByText(/أدخل مبلغاً صحيحاً/)).toBeInTheDocument();
    expect(api.of("POST", "/api/transactions")).toHaveLength(0);
  });
  it("requires a customer for a credit sale and explains what credit means", async () => {
    const api = mockFetch(list());
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "300000");
    await userEvent.type(within(dlg).getByLabelText(/الوصف/), "بيع آجل");
    await userEvent.selectOptions(within(dlg).getByLabelText(/طريقة الدفع/), "credit");
    expect(within(dlg).getByText(/يزيد دين الزبون ولا يُحسب كمبلغ مقبوض/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(within(dlg).getByText("اختر الزبون")).toBeInTheDocument();
    expect(api.of("POST", "/api/transactions")).toHaveLength(0);
  });
  it("adapts to the type: customer payment needs a customer and cannot be on credit; expense has no party", async () => {
    mockFetch(list());
    renderAt("/transactions");
    const dlg = await openAdd();
    const type = within(dlg).getByLabelText(/نوع المعاملة/);
    await userEvent.selectOptions(type, "customer_payment");
    expect(within(dlg).getByLabelText(/الزبون/)).toBeInTheDocument();
    const methods = within(within(dlg).getByLabelText(/طريقة الدفع/))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(methods).not.toContain("آجل");
    await userEvent.selectOptions(type, "expense");
    expect(within(dlg).queryByLabelText(/الزبون/)).not.toBeInTheDocument();
    expect(within(dlg).queryByLabelText(/المورد/)).not.toBeInTheDocument();
    await userEvent.selectOptions(type, "supplier_payment");
    expect(within(dlg).getByLabelText(/المورد/)).toBeInTheDocument();
  });
  it("switching away from credit-capable types resets an invalid credit method", async () => {
    mockFetch(list());
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.selectOptions(within(dlg).getByLabelText(/طريقة الدفع/), "credit");
    await userEvent.selectOptions(within(dlg).getByLabelText(/نوع المعاملة/), "expense");
    expect(within(dlg).getByLabelText(/طريقة الدفع/).value).toBe("cash");
  });
  it("creates a transaction with the parsed amount and refreshes the list", async () => {
    const api = mockFetch({ ...list(), "POST /api/transactions": { id: 999 } });
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "1,250,000");
    await userEvent.type(within(dlg).getByLabelText(/الوصف/), "بيع جديد");
    await userEvent.type(within(dlg).getByLabelText(/المرجع/), "INV-77");
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    await waitFor(() => expect(api.of("POST", "/api/transactions")).toHaveLength(1));
    expect(api.of("POST", "/api/transactions")[0].body).toMatchObject({
      type: "sale",
      amount: 1250000,
      description: "بيع جديد",
      payment_method: "cash",
      reference: "INV-77",
      customer_id: null,
      supplier_id: null,
      reconciliation_status: "reconciled",
      date: "2026-10-15",
    });
    expect(await screen.findByText("تمت إضافة المعاملة")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.of("GET", "/api/transactions").length).toBeGreaterThan(1); // list reloaded
  });
  it("maps server field errors onto the form fields", async () => {
    mockFetch({
      ...list(),
      "POST /api/transactions": fail(422, "validation_error", "بيانات الطلب غير صالحة", [
        { field: "reference", message: "المرجع غير مقبول من الخادم" },
      ]),
    });
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "5000");
    await userEvent.type(within(dlg).getByLabelText(/الوصف/), "x");
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(await within(dlg).findByText("المرجع غير مقبول من الخادم")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // stays open so nothing is lost
  });
  it("shows business-rule errors that have no field as a form-level alert", async () => {
    mockFetch({ ...list(), "POST /api/transactions": fail(422, "business_rule", "البيع بالآجل يحتاج إلى زبون") });
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.type(within(dlg).getByLabelText(/المبلغ/), "5000");
    await userEvent.type(within(dlg).getByLabelText(/الوصف/), "x");
    await userEvent.click(within(dlg).getByRole("button", { name: "إضافة المعاملة" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("البيع بالآجل يحتاج إلى زبون");
  });
  it("creates a new customer inline and selects it", async () => {
    const api = mockFetch({ ...list(), "POST /api/customers": { id: 4242, name: "زبون جديد" } });
    renderAt("/transactions");
    const dlg = await openAdd();
    await userEvent.selectOptions(within(dlg).getByLabelText(/طريقة الدفع/), "credit");
    await userEvent.click(within(dlg).getByRole("button", { name: /إضافة جديد/ }));
    await userEvent.type(within(dlg).getByLabelText(/اسم الزبون الجديد/), "زبون جديد");
    await userEvent.click(within(dlg).getByRole("button", { name: "حفظ" }));
    await waitFor(() => expect(api.of("POST", "/api/customers")[0].body).toEqual({ name: "زبون جديد" }));
  });
  it("edits an existing transaction: prefilled, then PUT to its id", async () => {
    const t = page.items.find((x) => x.type === "sale" && x.payment_method === "cash");
    const api = mockFetch({ ...list(), [`PUT /api/transactions/${t.id}`]: t });
    renderAt("/transactions");
    await userEvent.click(await screen.findByLabelText(`تعديل المعاملة ${t.id}`));
    const dlg = await screen.findByRole("dialog", { name: "تعديل المعاملة" });
    expect(within(dlg).getByLabelText(/المبلغ/).value).toBe(t.amount_iqd.toLocaleString("en-US"));
    expect(within(dlg).getByLabelText(/الوصف/).value).toBe(t.description);
    const desc = within(dlg).getByLabelText(/الوصف/);
    await userEvent.clear(desc);
    await userEvent.type(desc, "وصف معدّل");
    await userEvent.click(within(dlg).getByRole("button", { name: "حفظ التعديلات" }));
    await waitFor(() => expect(api.of("PUT", `/api/transactions/${t.id}`)).toHaveLength(1));
    expect(api.of("PUT", `/api/transactions/${t.id}`)[0].body).toMatchObject({
      description: "وصف معدّل",
      amount: t.amount_iqd,
      type: "sale",
    });
    expect(await screen.findByText("تم حفظ التعديلات")).toBeInTheDocument();
  });
  it("closes on Escape", async () => {
    mockFetch(list());
    renderAt("/transactions");
    await openAdd();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
describe("Delete", () => {
  it("asks for confirmation, shows what will be deleted, and does nothing if cancelled", async () => {
    const api = mockFetch(list());
    renderAt("/transactions");
    const t = page.items[0];
    await userEvent.click(await screen.findByLabelText(`حذف المعاملة ${t.id}`));
    const dlg = await screen.findByRole("dialog", { name: "حذف المعاملة" });
    expect(within(dlg).getByText(new RegExp(t.description.slice(0, 8)))).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "تراجع" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.of("DELETE", `/api/transactions/${t.id}`)).toHaveLength(0);
  });
  it("deletes after confirmation and reloads", async () => {
    const t = page.items[0];
    const api = mockFetch({ ...list(), [`DELETE /api/transactions/${t.id}`]: { deleted: t.id } });
    renderAt("/transactions");
    await userEvent.click(await screen.findByLabelText(`حذف المعاملة ${t.id}`));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "حذف المعاملة" })).getByRole("button", { name: "حذف نهائي" }));
    expect(await screen.findByText("تم حذف المعاملة")).toBeInTheDocument();
    expect(api.of("DELETE", `/api/transactions/${t.id}`)).toHaveLength(1);
    expect(api.of("GET", "/api/transactions").length).toBeGreaterThan(1);
  });
  it("offers 'exclude' as a reversible alternative that keeps the record", async () => {
    const t = page.items[0];
    const api = mockFetch({ ...list(), [`PUT /api/transactions/${t.id}`]: t });
    renderAt("/transactions");
    await userEvent.click(await screen.findByLabelText(`حذف المعاملة ${t.id}`));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /استبعاد من الحسابات/ }));
    await waitFor(() => expect(api.of("PUT", `/api/transactions/${t.id}`)).toHaveLength(1));
    expect(api.of("PUT", `/api/transactions/${t.id}`)[0].body).toMatchObject({
      reconciliation_status: "excluded",
      amount: t.amount_iqd,
      type: t.type,
    });
    expect(api.of("DELETE", `/api/transactions/${t.id}`)).toHaveLength(0);
  });
  it("reports a failed delete without closing silently", async () => {
    const t = page.items[0];
    mockFetch({ ...list(), [`DELETE /api/transactions/${t.id}`]: fail(404, "not_found", "المعاملة غير موجودة") });
    renderAt("/transactions");
    await userEvent.click(await screen.findByLabelText(`حذف المعاملة ${t.id}`));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "حذف نهائي" }));
    expect(await screen.findByText("المعاملة غير موجودة")).toBeInTheDocument();
  });
});

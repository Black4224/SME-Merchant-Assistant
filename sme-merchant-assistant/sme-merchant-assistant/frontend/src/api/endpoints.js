import { request } from "./client";
export const api = {
  health: () => request("/api/health"),
  settings: () => request("/api/settings"),
  updateSettings: (body) => request("/api/settings", { method: "PUT", body }),
  resetDemo: () => request("/api/settings/reset-demo", { method: "POST", body: { confirm: "RESET" } }),
  dashboard: (q) => request("/api/dashboard/summary", { query: q }),
  transactions: (q) => request("/api/transactions", { query: q }),
  createTransaction: (body) => request("/api/transactions", { method: "POST", body }),
  updateTransaction: (id, body) => request(`/api/transactions/${id}`, { method: "PUT", body }),
  deleteTransaction: (id) => request(`/api/transactions/${id}`, { method: "DELETE" }),
  previewImport: (file, mapping) => {
    const f = new FormData();
    f.append("file", file);
    if (mapping) f.append("mapping", JSON.stringify(mapping));
    return request("/api/import/csv/preview", { method: "POST", form: f });
  },
  confirmImport: (file, opts) => {
    const f = new FormData();
    f.append("file", file);
    if (opts.mapping) f.append("mapping", JSON.stringify(opts.mapping));
    f.append("skip_invalid", String(opts.skipInvalid));
    f.append("expected_sha256", opts.sha256);
    return request("/api/import/csv/confirm", { method: "POST", form: f });
  },
  customers: (q = {}) => request("/api/customers", { query: { page_size: 100, ...q } }),
  createCustomer: (name) => request("/api/customers", { method: "POST", body: { name } }),
  customerDebts: (id) => request(`/api/customers/${id}/debts`),
  recordPayment: (id, body) => request(`/api/customers/${id}/payments`, { method: "POST", body }),
  suppliers: () => request("/api/suppliers"),
  createSupplier: (name) => request("/api/suppliers", { method: "POST", body: { name } }),
  categories: () => request("/api/categories"),
  reportsSummary: (q) => request("/api/reports/summary", { query: q }),
  debtsReport: () => request("/api/reports/debts"),
  anomaliesReport: (q = {}) => request("/api/reports/anomalies", { query: q }),
  cashflow: (horizon_days = 30) => request("/api/reports/cashflow", { query: { horizon_days } }),
  assistantStatus: () => request("/api/assistant/status"),
  chat: (message, history) => request("/api/assistant/chat", { method: "POST", body: { message, history } }),
};

export class ApiError extends Error {
  status;
  code;
  details;
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.name = "ApiError";
  }
  /** Backend validation errors keyed by form field (`details: [{field, message}]`). */
  get fieldErrors() {
    const out = {};
    if (Array.isArray(this.details)) for (const d of this.details) if (d?.field) out[d.field] = d.message;
    return out;
  }
}
const BASE = import.meta.env.VITE_API_URL ?? "";
export function buildQuery(q) {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
export async function request(path, opts = {}) {
  const init = { method: opts.method ?? "GET", headers: {} };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(`${BASE}${path}${buildQuery(opts.query)}`, init);
  } catch {
    throw new ApiError(0, "network", "تعذّر الاتصال بالخادم. تأكد أن الخادم يعمل ثم أعد المحاولة.");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = data?.error;
    throw new ApiError(res.status, e?.code ?? "http_error", e?.message ?? `حدث خطأ غير متوقع (${res.status})`, e?.details);
  }
  return data;
}

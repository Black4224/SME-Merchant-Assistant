import { Plus } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { fmtNum, parseAmountInput, todayIso } from "../lib/format";
import { METHOD_LABEL, STATUS_LABEL, TYPE_LABEL, TYPE_RULES } from "../lib/labels";
import { useLookups } from "../lib/lookups";
import { useSettings } from "../lib/settings";
import { Modal } from "./Modal";
import { useToast } from "./Toast";
import { Button, Field, inputCls } from "./ui";
const CATEGORY_KIND = { sale: "sale", expense: "expense", supplier_purchase: "purchase" };
export function validateForm(f) {
  const e = {};
  const rule = TYPE_RULES[f.type];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date) || Number.isNaN(Date.parse(f.date))) e.date = "اختر تاريخاً صحيحاً";
  if (parseAmountInput(f.amount) === null) e.amount = "أدخل مبلغاً صحيحاً بالدينار أكبر من صفر، بدون كسور";
  if (!f.description.trim()) e.description = "الوصف مطلوب";
  else if (f.description.length > 255) e.description = "الوصف أطول من 255 حرفاً";
  if (f.reference.length > 64) e.reference = "المرجع أطول من 64 حرفاً";
  if (f.payment_method === "credit" && !rule.credit) e.payment_method = "هذا النوع لا يكون آجلاً";
  if ((rule.customer === "required" || (rule.customer === "optional" && f.payment_method === "credit")) && !f.customer_id)
    e.customer_id = "اختر الزبون";
  if ((rule.supplier === "required" || (rule.supplier === "optional" && f.payment_method === "credit")) && !f.supplier_id)
    e.supplier_id = "اختر المورد";
  return e;
}
function PartyPicker({ label, value, onChange, options, error, required, onCreate }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    setErr("");
    try {
      const id = await onCreate(name.trim());
      onChange(String(id));
      setAdding(false);
      setName("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "تعذّر الإضافة");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <Field
        label={
          <>
            {label}
            {required && <span className="text-neg"> *</span>}
          </>
        }
        error={error}
      >
        <select className={inputCls(!!error)} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{required ? "— اختر —" : "— بدون —"}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </Field>
      {!adding ? (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-info hover:underline"
        >
          <Plus className="size-3.5" aria-hidden />
          إضافة جديد
        </button>
      ) : (
        <div className="mt-2 flex gap-2">
          <input
            className={inputCls(!!err)}
            placeholder="الاسم"
            aria-label={`اسم ${label} الجديد`}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="button" variant="primary" onClick={create} loading={busy} disabled={!name.trim()}>
            حفظ
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setAdding(false);
              setErr("");
            }}
          >
            إلغاء
          </Button>
        </div>
      )}
      {err && (
        <p role="alert" className="mt-1 text-sm text-neg">
          {err}
        </p>
      )}
    </div>
  );
}
function formFromTxn(t, defaultDate) {
  if (t) {
    return {
      date: t.date,
      type: t.type,
      amount: fmtNum(t.amount_iqd),
      description: t.description,
      payment_method: t.payment_method,
      customer_id: t.customer ? String(t.customer.id) : "",
      supplier_id: t.supplier ? String(t.supplier.id) : "",
      category_id: t.category ? String(t.category.id) : "",
      reference: t.reference ?? "",
      status: t.reconciliation_status,
    };
  }
  return {
    date: defaultDate,
    type: "sale",
    amount: "",
    description: "",
    payment_method: "cash",
    customer_id: "",
    supplier_id: "",
    category_id: "",
    reference: "",
    status: "reconciled",
  };
}

function TransactionFormDialog({ initial, onClose, onSaved }) {
  const { settings } = useSettings();
  const toast = useToast();
  const lookups = useLookups();
  const [f, setF] = useState(() => formFromTxn(initial, settings?.reference_date ?? todayIso()));
  const [errors, setErrors] = useState({});
  const [general, setGeneral] = useState("");
  const [busy, setBusy] = useState(false);
  const rule = TYPE_RULES[f.type];
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const changeType = (t) =>
    setF((s) => ({
      ...s,
      type: t,
      payment_method: s.payment_method === "credit" && !TYPE_RULES[t].credit ? "cash" : s.payment_method,
      customer_id: TYPE_RULES[t].customer === "none" ? "" : s.customer_id,
      supplier_id: TYPE_RULES[t].supplier === "none" ? "" : s.supplier_id,
      category_id: "",
    }));
  const kind = CATEGORY_KIND[f.type];
  const methods = Object.keys(METHOD_LABEL).filter((m) => m !== "credit" || rule.credit);
  const customerRequired = rule.customer === "required" || (rule.customer === "optional" && f.payment_method === "credit");
  const supplierRequired = rule.supplier === "required" || (rule.supplier === "optional" && f.payment_method === "credit");
  const submit = async (ev) => {
    ev.preventDefault();
    const local = validateForm(f);
    setErrors(local);
    setGeneral("");
    if (Object.keys(local).length) return;
    setBusy(true);
    const body = {
      date: f.date,
      type: f.type,
      amount: parseAmountInput(f.amount),
      description: f.description.trim(),
      payment_method: f.payment_method,
      reference: f.reference.trim() || null,
      customer_id: rule.customer !== "none" && f.customer_id ? Number(f.customer_id) : null,
      supplier_id: rule.supplier !== "none" && f.supplier_id ? Number(f.supplier_id) : null,
      category_id: kind && f.category_id ? Number(f.category_id) : null,
      reconciliation_status: f.status,
    };
    try {
      if (initial) await api.updateTransaction(initial.id, body);
      else await api.createTransaction(body);
      toast(initial ? "تم حفظ التعديلات" : "تمت إضافة المعاملة");
      onSaved();
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        const fe = e.fieldErrors;
        const map = { customer_id: "customer_id", supplier_id: "supplier_id" };
        setErrors(Object.fromEntries(Object.entries(fe).map(([k, v]) => [map[k] ?? k, v])));
        if (!Object.keys(fe).length) setGeneral(e.message);
      } else setGeneral("حدث خطأ غير متوقع");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title={initial ? "تعديل المعاملة" : "إضافة معاملة"}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            إلغاء
          </Button>
          <Button variant="primary" type="submit" form="txn-form" loading={busy}>
            {initial ? "حفظ التعديلات" : "إضافة المعاملة"}
          </Button>
        </>
      }
    >
      <form id="txn-form" onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
        {general && (
          <p
            role="alert"
            className="rounded-control border border-[#f2c5c3] bg-neg-bg px-3 py-2 text-sm font-medium text-neg sm:col-span-2"
          >
            {general}
          </p>
        )}
        <Field label="نوع المعاملة" error={errors.type}>
          <select className={inputCls(!!errors.type)} value={f.type} onChange={(e) => changeType(e.target.value)}>
            {Object.keys(TYPE_LABEL).map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="التاريخ" error={errors.date}>
          <input type="date" className={inputCls(!!errors.date)} value={f.date} onChange={(e) => set("date", e.target.value)} />
        </Field>
        <Field label="المبلغ (دينار)" error={errors.amount} hint="أرقام صحيحة بدون كسور، مثال: 1,250,000">
          <input
            inputMode="numeric"
            className={inputCls(!!errors.amount) + " num text-start"}
            value={f.amount}
            onChange={(e) => set("amount", e.target.value)}
            placeholder="0"
          />
        </Field>
        <Field label="طريقة الدفع" error={errors.payment_method}>
          <select
            className={inputCls(!!errors.payment_method)}
            value={f.payment_method}
            onChange={(e) => set("payment_method", e.target.value)}
          >
            {methods.map((m) => (
              <option key={m} value={m}>
                {METHOD_LABEL[m]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="الوصف" error={errors.description} className="sm:col-span-2">
          <input
            className={inputCls(!!errors.description)}
            value={f.description}
            onChange={(e) => set("description", e.target.value)}
            maxLength={300}
          />
        </Field>
        {rule.customer !== "none" && (
          <PartyPicker
            label="الزبون"
            required={customerRequired}
            value={f.customer_id}
            onChange={(v) => set("customer_id", v)}
            options={lookups.customers}
            error={errors.customer_id}
            onCreate={async (n) => {
              const r = await api.createCustomer(n);
              lookups.reload();
              return r.id;
            }}
          />
        )}
        {rule.supplier !== "none" && (
          <PartyPicker
            label="المورد"
            required={supplierRequired}
            value={f.supplier_id}
            onChange={(v) => set("supplier_id", v)}
            options={lookups.suppliers}
            error={errors.supplier_id}
            onCreate={async (n) => {
              const r = await api.createSupplier(n);
              lookups.reload();
              return r.id;
            }}
          />
        )}
        {kind && (
          <Field label="التصنيف">
            <select className={inputCls()} value={f.category_id} onChange={(e) => set("category_id", e.target.value)}>
              <option value="">— بدون —</option>
              {lookups.categories
                .filter((c) => c.kind === kind)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </Field>
        )}
        <Field label="المرجع (رقم فاتورة / وصل)" error={errors.reference}>
          <input className={inputCls(!!errors.reference)} value={f.reference} onChange={(e) => set("reference", e.target.value)} />
        </Field>
        <Field label="حالة المطابقة" hint={f.status === "excluded" ? "المعاملات المستبعدة لا تدخل في أي حساب." : undefined}>
          <select className={inputCls()} value={f.status} onChange={(e) => set("status", e.target.value)}>
            {Object.keys(STATUS_LABEL).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </Field>
        {f.payment_method === "credit" && (
          <p className="rounded-control bg-warn-bg px-3 py-2 text-sm text-warn sm:col-span-2">
            {f.type === "sale"
              ? "البيع الآجل يزيد دين الزبون ولا يُحسب كمبلغ مقبوض حتى يسدّد الزبون."
              : "الشراء الآجل يزيد المستحق للمورد ولا يخرج نقد حتى تسدّد."}
          </p>
        )}
      </form>
    </Modal>
  );
}

/** Mounted only while open (and keyed per transaction), so the form always starts from fresh state. */
export function TransactionForm({ open, initial, onClose, onSaved }) {
  return open ? <TransactionFormDialog key={initial?.id ?? "new"} initial={initial} onClose={onClose} onSaved={onSaved} /> : null;
}

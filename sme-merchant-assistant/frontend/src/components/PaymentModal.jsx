import { useState } from "react";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { fmtIqd, parseAmountInput, todayIso } from "../lib/format";
import { useSettings } from "../lib/settings";
import { Modal } from "./Modal";
import { Money } from "./Money";
import { useToast } from "./Toast";
import { Button, Field, inputCls } from "./ui";
function PaymentForm({ customer, onClose, onSaved }) {
  const { settings } = useSettings();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(settings?.reference_date ?? todayIso());
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [allowOver, setAllowOver] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);
  const owes = Math.max(customer.outstanding, 0);
  const submit = async (e) => {
    e.preventDefault();
    const parsed = parseAmountInput(amount);
    if (parsed === null) {
      setFieldErr({ amount: "أدخل مبلغاً صحيحاً بالدينار أكبر من صفر، بدون كسور" });
      return;
    }
    setFieldErr({});
    setError(null);
    setBusy(true);
    try {
      const r = await api.recordPayment(customer.id, {
        amount: parsed,
        date,
        payment_method: method,
        reference: reference.trim() || null,
        allow_overpayment: allowOver,
      });
      toast(`تم تسجيل الدفعة. المتبقي على الزبون: ${fmtIqd(r.outstanding_after, settings?.currency_display)}`);
      onSaved();
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        setFieldErr(err.fieldErrors);
        if (!Object.keys(err.fieldErrors).length) setError(err);
      } else setError("حدث خطأ غير متوقع");
    } finally {
      setBusy(false);
    }
  };
  const overpay = error instanceof ApiError && error.code === "overpayment";
  return (
    <Modal
      open
      onClose={onClose}
      title={`تسجيل دفعة من ${customer.name}`}
      size="md"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            إلغاء
          </Button>
          <Button variant="primary" type="submit" form="pay-form" loading={busy}>
            تسجيل الدفعة
          </Button>
        </>
      }
    >
      <form id="pay-form" onSubmit={submit} noValidate className="space-y-4">
        <div className="rounded-control bg-page px-3 py-2.5 text-sm">
          <p>
            الدين الحالي على الزبون: <Money value={owes} tone={owes > 0 ? "neg" : "none"} className="font-bold" />
          </p>
          <p className="mt-1 text-muted">الدفعة تخفض دين الزبون فقط، ولا تُحسب مبيعات جديدة ولا تغيّر إجمالي المبيعات.</p>
        </div>
        {error && (
          <p role="alert" className="rounded-control border border-[#f2c5c3] bg-neg-bg px-3 py-2 text-sm font-medium text-neg">
            {typeof error === "string" ? error : error.message}
          </p>
        )}
        {overpay && (
          <label className="flex items-start gap-2 rounded-control border border-line px-3 py-2 text-sm">
            <input type="checkbox" className="mt-1 size-4" checked={allowOver} onChange={(e) => setAllowOver(e.target.checked)} />
            <span>السماح بدفعة أكبر من الدين (يصبح للزبون رصيد لصالحه). ثم اضغط «تسجيل الدفعة» مرة ثانية.</span>
          </label>
        )}
        <Field label="المبلغ (دينار)" error={fieldErr.amount}>
          <div className="flex gap-2">
            <input
              inputMode="numeric"
              autoFocus
              className={inputCls(!!fieldErr.amount) + " num text-start"}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0"
            />
            {owes > 0 && (
              <Button type="button" onClick={() => setAmount(owes.toLocaleString("en-US"))} className="shrink-0">
                كامل الدين
              </Button>
            )}
          </div>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="تاريخ الدفعة" error={fieldErr.date}>
            <input type="date" className={inputCls(!!fieldErr.date)} value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="طريقة الدفع">
            <select className={inputCls()} value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="cash">نقد</option>
              <option value="digital">محفظة إلكترونية</option>
              <option value="bank">بنك / بطاقة</option>
            </select>
          </Field>
        </div>
        <Field label="المرجع (رقم وصل، اختياري)" error={fieldErr.reference}>
          <input className={inputCls(!!fieldErr.reference)} value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}

/** Mounts a fresh form for each customer, so no state needs to be reset by an effect. */
export function PaymentModal({ customer, onClose, onSaved }) {
  return customer ? <PaymentForm key={customer.id} customer={customer} onClose={onClose} onSaved={onSaved} /> : null;
}

import { Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { PageHeader } from "../components/Layout";
import { Modal } from "../components/Modal";
import { Money } from "../components/Money";
import { PaymentModal } from "../components/PaymentModal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Segmented, Spinner, TableWrap, inputCls, td, th } from "../components/ui";
import { fmtDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";
export function Customers() {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const list = useAsync(() => api.customers({ q, has_debt: filter === "all" ? undefined : filter === "debt" }), [q, filter]);
  const totals = useAsync(() => api.debtsReport(), []);
  const [paying, setPaying] = useState(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [addErr, setAddErr] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => {
    list.reload();
    totals.reload();
  };
  const add = async () => {
    setBusy(true);
    setAddErr("");
    try {
      await api.createCustomer(name.trim());
      toast("تمت إضافة الزبون");
      setAdding(false);
      setName("");
      refresh();
    } catch (e) {
      setAddErr(e instanceof ApiError ? e.message : "تعذّرت الإضافة");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader
        title="الزبائن والديون"
        subtitle="البيع الآجل يزيد دين الزبون، والتسديد يخفضه ولا يُحسب مبيعات."
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden />
            إضافة زبون
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-panel border border-line bg-surface p-4">
          <p className="text-sm font-semibold text-muted">إجمالي الديون المستحقة</p>
          <p className="mt-1 text-2xl font-bold">{totals.data ? <Money value={totals.data.total_outstanding} /> : "…"}</p>
        </div>
        <div className="rounded-panel border border-line bg-surface p-4">
          <p className="text-sm font-semibold text-muted">منها متأخر (أكثر من {totals.data?.credit_terms_days ?? 30} يوماً)</p>
          <p className="mt-1 text-2xl font-bold">
            {totals.data ? <Money value={totals.data.total_overdue} tone={totals.data.total_overdue > 0 ? "neg" : "none"} /> : "…"}
          </p>
        </div>
        <div className="rounded-panel border border-line bg-surface p-4">
          <p className="text-sm font-semibold text-muted">عدد الزبائن المدينين</p>
          <p className="mt-1 text-2xl font-bold num">{totals.data ? totals.data.customers.length : "…"}</p>
        </div>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative block min-w-56 flex-1">
            <span className="sr-only">بحث عن زبون</span>
            <Search className="pointer-events-none absolute start-3 top-3 size-4 text-faint" aria-hidden />
            <input className={inputCls() + " ps-9"} placeholder="ابحث باسم الزبون" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <Segmented
            label="تصفية الزبائن"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "الكل" },
              { value: "debt", label: "عليهم دين" },
              { value: "clear", label: "بدون دين" },
            ]}
          />
        </div>
      </Card>

      {list.error && <ErrorBanner error={list.error} onRetry={list.reload} />}
      <Card pad={false}>
        {!list.data && list.loading ? (
          <Spinner />
        ) : list.data && list.data.items.length === 0 ? (
          <EmptyState title="لا يوجد زبائن مطابقون" hint="غيّر البحث أو أضف زبوناً جديداً." />
        ) : (
          list.data && (
            <TableWrap>
              <thead>
                <tr>
                  <th className={th}>الزبون</th>
                  <th className={th}>المبيعات الآجلة</th>
                  <th className={th}>المسدَّد</th>
                  <th className={th}>المستحق</th>
                  <th className={th}>المتأخر</th>
                  <th className={th}>آخر دفعة</th>
                  <th className={th}>
                    <span className="sr-only">إجراء</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((c) => (
                  <tr key={c.customer_id}>
                    <td className={td}>
                      <Link className="font-semibold hover:underline" to={`/customers/${c.customer_id}`}>
                        {c.name}
                      </Link>
                      {c.open_invoices_count > 0 && (
                        <span className="block text-xs text-muted">
                          فواتير مفتوحة: <span className="num">{c.open_invoices_count}</span>
                        </span>
                      )}
                    </td>
                    <td className={td}>
                      <Money value={c.credit_sales_total} />
                    </td>
                    <td className={td}>
                      <Money value={c.payments_total} tone="pos" />
                    </td>
                    <td className={td}>
                      <Money value={Math.max(c.outstanding, 0)} tone={c.outstanding > 0 ? "neg" : "none"} className="font-bold" />
                      {c.outstanding < 0 && <Badge tone="info">رصيد للزبون</Badge>}
                    </td>
                    <td className={td}>
                      {c.overdue_amount > 0 ? <Money value={c.overdue_amount} tone="neg" /> : <span className="text-faint">—</span>}
                    </td>
                    <td className={td}>{fmtDate(c.last_payment_date)}</td>
                    <td className={td}>
                      <Button className="h-9" onClick={() => setPaying(c)}>
                        تسجيل دفعة
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )
        )}
      </Card>

      <PaymentModal
        customer={paying ? { id: paying.customer_id, name: paying.name, outstanding: paying.outstanding } : null}
        onClose={() => setPaying(null)}
        onSaved={refresh}
      />
      <Modal
        open={adding}
        title="إضافة زبون"
        onClose={() => setAdding(false)}
        size="sm"
        footer={
          <>
            <Button onClick={() => setAdding(false)}>إلغاء</Button>
            <Button variant="primary" onClick={add} loading={busy} disabled={!name.trim()}>
              إضافة
            </Button>
          </>
        }
      >
        <Field label="اسم الزبون" error={addErr}>
          <input
            autoFocus
            className={inputCls(!!addErr)}
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && void add()}
          />
        </Field>
      </Modal>
    </>
  );
}

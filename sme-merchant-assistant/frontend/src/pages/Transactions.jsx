import { ArrowDown, ArrowUp, FileUp, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { ImportWizard } from "../components/ImportWizard";
import { PageHeader } from "../components/Layout";
import { ConfirmDialog } from "../components/Modal";
import { Money } from "../components/Money";
import { TransactionForm } from "../components/TransactionForm";
import { useToast } from "../components/Toast";
import { FlagBadges, MethodBadge, TypeBadge, partyName } from "../components/txn";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner, TableWrap, cx, inputCls, td, th } from "../components/ui";
import { fmtDateShort, fmtIqd } from "../lib/format";
import { METHOD_LABEL, STATUS_LABEL, TYPE_LABEL } from "../lib/labels";
import { useAsync } from "../lib/useAsync";
function SortIcon({ active, order }) {
  if (!active) return null;
  return order === "desc" ? <ArrowDown className="inline size-3.5" aria-hidden /> : <ArrowUp className="inline size-3.5" aria-hidden />;
}

const FILTER_KEYS = ["q", "type", "payment_method", "status", "date_from", "date_to", "min_amount", "max_amount"];
export function Transactions() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const get = (k) => params.get(k) ?? "";
  const page = Math.max(1, Number(get("page")) || 1);
  const pageSize = Number(get("page_size")) || 25;
  const sort = get("sort") || "date";
  const order = get("order") || "desc";
  const update = (patch, resetPage = true) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) v ? next.set(k, v) : next.delete(k);
    if (resetPage) next.delete("page");
    setParams(next, { replace: true });
  };
  const [q, setQ] = useState(get("q"));
  useEffect(() => {
    const t = setTimeout(() => q !== get("q") && update({ q }), 350);
    return () => clearTimeout(t); /* eslint-disable-next-line */
  }, [q]);
  const query = { ...Object.fromEntries(FILTER_KEYS.map((k) => [k, get(k)])), sort, order, page, page_size: pageSize };
  const { data, error, loading, reload } = useAsync(() => api.transactions(query), [params.toString()]);
  const [editing, setEditing] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const hasFilters = FILTER_KEYS.some((k) => get(k));
  const clear = () => {
    setQ("");
    setParams(new URLSearchParams(), { replace: true });
  };
  const toggleSort = (col) => update(sort === col ? { order: order === "desc" ? "asc" : "desc" } : { sort: col, order: "desc" });
  const act = async (fn, okMsg) => {
    setBusy(true);
    try {
      await fn();
      toast(okMsg);
      setDeleting(null);
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "حدث خطأ غير متوقع", "err");
    } finally {
      setBusy(false);
    }
  };
  const exclude = (t) =>
    api.updateTransaction(t.id, {
      date: t.date,
      type: t.type,
      amount: t.amount_iqd,
      description: t.description,
      payment_method: t.payment_method,
      reference: t.reference,
      customer_id: t.customer?.id ?? null,
      supplier_id: t.supplier?.id ?? null,
      category_id: t.category?.id ?? null,
      reconciliation_status: "excluded",
    });
  return (
    <>
      <PageHeader
        title="المعاملات"
        subtitle={
          data ? (
            <>
              إجمالي النتائج: <span className="num">{data.total}</span>
            </>
          ) : undefined
        }
        actions={
          <>
            <Button onClick={() => setImportOpen(true)}>
              <FileUp className="size-4" aria-hidden />
              استيراد CSV
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="size-4" aria-hidden />
              إضافة معاملة
            </Button>
          </>
        }
      />

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="relative block sm:col-span-2">
            <span className="sr-only">بحث</span>
            <Search className="pointer-events-none absolute start-3 top-3 size-4 text-faint" aria-hidden />
            <input
              className={inputCls() + " ps-9"}
              placeholder="ابحث بالوصف أو المرجع أو اسم الزبون/المورد"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <select aria-label="النوع" className={inputCls()} value={get("type")} onChange={(e) => update({ type: e.target.value })}>
            <option value="">كل الأنواع</option>
            {Object.entries(TYPE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            aria-label="طريقة الدفع"
            className={inputCls()}
            value={get("payment_method")}
            onChange={(e) => update({ payment_method: e.target.value })}
          >
            <option value="">كل طرق الدفع</option>
            {Object.entries(METHOD_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            aria-label="حالة المطابقة"
            className={inputCls()}
            value={get("status")}
            onChange={(e) => update({ status: e.target.value })}
          >
            <option value="">كل الحالات</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <span className="shrink-0 text-muted">من</span>
            <input type="date" className={inputCls()} value={get("date_from")} onChange={(e) => update({ date_from: e.target.value })} />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="shrink-0 text-muted">إلى</span>
            <input type="date" className={inputCls()} value={get("date_to")} onChange={(e) => update({ date_to: e.target.value })} />
          </label>
          <input
            aria-label="أقل مبلغ"
            inputMode="numeric"
            className={inputCls() + " num text-start"}
            placeholder="أقل مبلغ"
            value={get("min_amount")}
            onChange={(e) => update({ min_amount: e.target.value })}
          />
          <input
            aria-label="أعلى مبلغ"
            inputMode="numeric"
            className={inputCls() + " num text-start"}
            placeholder="أعلى مبلغ"
            value={get("max_amount")}
            onChange={(e) => update({ max_amount: e.target.value })}
          />
        </div>
        {hasFilters && (
          <Button variant="ghost" className="mt-3 h-9" onClick={clear}>
            <X className="size-4" aria-hidden />
            مسح الفلاتر
          </Button>
        )}
      </Card>

      {error && <ErrorBanner error={error} onRetry={reload} />}

      <Card pad={false}>
        {!data && loading ? (
          <Spinner />
        ) : data && data.items.length === 0 ? (
          <EmptyState
            title={hasFilters ? "لا توجد معاملات تطابق الفلاتر" : "لا توجد معاملات بعد"}
            hint={hasFilters ? "غيّر الفلاتر أو امسحها لعرض كل المعاملات." : "أضف معاملة يدوياً أو استورد ملف CSV لتبدأ."}
            action={
              hasFilters ? (
                <Button onClick={clear}>مسح الفلاتر</Button>
              ) : (
                <Button variant="primary" onClick={() => setFormOpen(true)}>
                  إضافة معاملة
                </Button>
              )
            }
          />
        ) : (
          data && (
            <div className={cx(loading && "opacity-60 transition-opacity")} aria-busy={loading}>
              <TableWrap>
                <thead>
                  <tr>
                    <th className={th}>
                      <button className="font-semibold" onClick={() => toggleSort("date")} aria-label="ترتيب حسب التاريخ">
                        التاريخ <SortIcon active={sort === "date"} order={order} />
                      </button>
                    </th>
                    <th className={th}>النوع</th>
                    <th className={th}>الوصف</th>
                    <th className={th}>الطرف</th>
                    <th className={th}>الدفع</th>
                    <th className={th}>
                      <button className="font-semibold" onClick={() => toggleSort("amount")} aria-label="ترتيب حسب المبلغ">
                        المبلغ <SortIcon active={sort === "amount"} order={order} />
                      </button>
                    </th>
                    <th className={th}>
                      <span className="sr-only">إجراءات</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className={cx(t.reconciliation_status === "excluded" && "text-faint line-through decoration-faint/60")}>
                      <td className={td}>
                        {fmtDateShort(t.date)}
                        <span className="block text-xs text-faint num">#{t.id}</span>
                      </td>
                      <td className={td}>
                        <TypeBadge type={t.type} />
                      </td>
                      <td className={td}>
                        <span>{t.description}</span>
                        {t.reference && <span className="block text-xs text-muted num">{t.reference}</span>}
                        <span className="mt-1 flex flex-wrap gap-1">
                          {t.reconciliation_status !== "reconciled" && (
                            <Badge tone={t.reconciliation_status === "excluded" ? "neutral" : "warn"}>
                              {STATUS_LABEL[t.reconciliation_status]}
                            </Badge>
                          )}
                          <FlagBadges flags={t.flags.filter((f) => f.code !== "unreconciled")} />
                        </span>
                      </td>
                      <td className={td}>{partyName(t)}</td>
                      <td className={td}>
                        <MethodBadge method={t.payment_method} />
                      </td>
                      <td className={td}>
                        <Money value={t.amount_iqd} className="font-semibold" />
                      </td>
                      <td className={td}>
                        <div className="flex gap-1">
                          <button
                            className="rounded-control p-2 text-muted hover:bg-page hover:text-ink"
                            aria-label={`تعديل المعاملة ${t.id}`}
                            onClick={() => {
                              setEditing(t);
                              setFormOpen(true);
                            }}
                          >
                            <Pencil className="size-4" />
                          </button>
                          <button
                            className="rounded-control p-2 text-muted hover:bg-neg-bg hover:text-neg"
                            aria-label={`حذف المعاملة ${t.id}`}
                            onClick={() => setDeleting(t)}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
              <nav
                aria-label="الصفحات"
                className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-sm"
              >
                <span className="text-muted">
                  صفحة <span className="num">{data.page}</span> من <span className="num">{data.pages}</span>
                </span>
                <div className="flex items-center gap-2">
                  <select
                    aria-label="عدد الصفوف"
                    className={inputCls() + " h-9 w-auto"}
                    value={pageSize}
                    onChange={(e) => update({ page_size: e.target.value })}
                  >
                    {[25, 50, 100].map((n) => (
                      <option key={n} value={n}>
                        {n} صف
                      </option>
                    ))}
                  </select>
                  <Button className="h-9" disabled={page <= 1} onClick={() => update({ page: String(page - 1) }, false)}>
                    السابق
                  </Button>
                  <Button className="h-9" disabled={page >= data.pages} onClick={() => update({ page: String(page + 1) }, false)}>
                    التالي
                  </Button>
                </div>
              </nav>
            </div>
          )
        )}
      </Card>

      <TransactionForm open={formOpen} initial={editing} onClose={() => setFormOpen(false)} onSaved={reload} />
      <ImportWizard open={importOpen} onClose={() => setImportOpen(false)} onDone={reload} />
      <ConfirmDialog
        open={!!deleting}
        title="حذف المعاملة"
        danger
        confirmLabel="حذف نهائي"
        loading={busy}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && act(() => api.deleteTransaction(deleting.id), "تم حذف المعاملة")}
        extra={
          deleting && deleting.reconciliation_status !== "excluded" ? (
            <Button onClick={() => act(() => exclude(deleting), "تم استبعاد المعاملة من الحسابات")} disabled={busy}>
              استبعاد من الحسابات بدلاً من الحذف
            </Button>
          ) : undefined
        }
      >
        {deleting && (
          <>
            <p>هل تريد حذف هذه المعاملة نهائياً؟ لا يمكن التراجع.</p>
            <p className="rounded-control bg-page px-3 py-2">
              <b>{TYPE_LABEL[deleting.type]}</b> بمبلغ <span className="num">{fmtIqd(deleting.amount_iqd)}</span> بتاريخ{" "}
              {fmtDateShort(deleting.date)}: {deleting.description}
            </p>
            <p className="text-muted">إذا كنت تريد فقط إخراجها من الحسابات مع الاحتفاظ بسجلها (مثل معاملة مكررة)، اختر «استبعاد».</p>
          </>
        )}
      </ConfirmDialog>
    </>
  );
}

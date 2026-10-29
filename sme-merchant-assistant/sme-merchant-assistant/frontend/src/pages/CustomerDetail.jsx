import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { PageHeader } from "../components/Layout";
import { Money } from "../components/Money";
import { PaymentModal } from "../components/PaymentModal";
import { MethodBadge } from "../components/txn";
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner, TableWrap, td, th } from "../components/ui";
import { fmtDate } from "../lib/format";
import { useAsync } from "../lib/useAsync";
export function CustomerDetail() {
  const id = Number(useParams().id);
  const { data, error, loading, reload } = useAsync(() => api.customerDebts(id), [id]);
  const [paying, setPaying] = useState(false);
  if (error && !data)
    return (
      <>
        <Link to="/customers" className="inline-flex items-center gap-1 text-sm font-semibold text-info hover:underline">
          <ArrowRight className="size-4 rtl:rotate-0" aria-hidden />
          كل الزبائن
        </Link>
        <ErrorBanner error={error} onRetry={reload} />
      </>
    );
  if (!data) return <Spinner />;
  const b = data.balance;
  const history = [...data.history].reverse();
  return (
    <>
      <Link to="/customers" className="inline-flex items-center gap-1 text-sm font-semibold text-info hover:underline">
        <ArrowRight className="size-4" aria-hidden />
        كل الزبائن
      </Link>
      <PageHeader
        title={data.customer.name}
        subtitle={<>الأرصدة حتى {fmtDate(data.as_of)}</>}
        actions={
          <Button variant="primary" onClick={() => setPaying(true)} disabled={loading}>
            تسجيل دفعة
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          {
            l: "الدين الحالي",
            v: Math.max(b.outstanding, 0),
            tone: b.outstanding > 0 ? "neg" : "none",
            extra: b.outstanding < 0 ? <Badge tone="info">رصيد لصالح الزبون</Badge> : null,
          },
          { l: "منه متأخر", v: b.overdue_amount, tone: b.overdue_amount > 0 ? "neg" : "none" },
          { l: "إجمالي المبيعات الآجلة", v: b.credit_sales_total, tone: "none" },
          { l: "إجمالي ما سدّده", v: b.payments_total, tone: "pos" },
        ].map((k) => (
          <div key={k.l} className="rounded-panel border border-line bg-surface p-4">
            <p className="text-sm font-semibold text-muted">{k.l}</p>
            <p className="mt-1 text-2xl font-bold">
              <Money value={k.v} tone={k.tone} /> {k.extra}
            </p>
          </div>
        ))}
      </div>

      <Card title="الفواتير الآجلة غير المسددة" pad={false}>
        {b.open_invoices.length === 0 ? (
          <EmptyState title="لا توجد فواتير مفتوحة" hint="هذا الزبون لا عليه دين حالياً." />
        ) : (
          <>
            <TableWrap>
              <thead>
                <tr>
                  <th className={th}>رقم المعاملة</th>
                  <th className={th}>التاريخ</th>
                  <th className={th}>عمر الفاتورة</th>
                  <th className={th}>مبلغ الفاتورة</th>
                  <th className={th}>المتبقي</th>
                  <th className={th}>الحالة</th>
                </tr>
              </thead>
              <tbody>
                {b.open_invoices.map((i) => (
                  <tr key={i.transaction_id}>
                    <td className={td}>
                      <span className="num">#{i.transaction_id}</span>
                    </td>
                    <td className={td}>{fmtDate(i.date)}</td>
                    <td className={td}>
                      <span className="num">{i.age_days}</span> يوماً
                    </td>
                    <td className={td}>
                      <Money value={i.original_amount} />
                    </td>
                    <td className={td}>
                      <Money value={i.remaining} tone="neg" className="font-bold" />
                    </td>
                    <td className={td}>{i.overdue ? <Badge tone="neg">متأخرة</Badge> : <Badge>ضمن المدة</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <p className="px-4 py-3 text-xs text-muted sm:px-5">
              تُوزَّع الدفعات على أقدم فاتورة أولاً. المتأخرة هي الفواتير التي مضى عليها أكثر من مدة الائتمان المحددة في الإعدادات.
            </p>
          </>
        )}
      </Card>

      <Card title="سجل الدين" pad={false}>
        <p className="border-b border-line px-4 py-3 text-sm text-muted sm:px-5">
          <Badge tone="warn">بيع آجل</Badge> يزيد الدين (لم يُقبض مال بعد). <Badge tone="pos">تسديد</Badge> يخفض الدين وليس مبيعات جديدة.
        </p>
        {history.length === 0 ? (
          <EmptyState title="لا توجد حركات بعد" />
        ) : (
          <TableWrap>
            <thead>
              <tr>
                <th className={th}>التاريخ</th>
                <th className={th}>الحركة</th>
                <th className={th}>الوصف</th>
                <th className={th}>الدفع</th>
                <th className={th}>أثرها على الدين</th>
                <th className={th}>الرصيد بعدها</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.transaction_id}>
                  <td className={td}>
                    {fmtDate(h.date)}
                    <span className="block text-xs text-faint num">#{h.transaction_id}</span>
                  </td>
                  <td className={td}>{h.kind === "credit_sale" ? <Badge tone="warn">بيع آجل</Badge> : <Badge tone="pos">تسديد</Badge>}</td>
                  <td className={td}>{h.description}</td>
                  <td className={td}>
                    <MethodBadge method={h.payment_method} />
                  </td>
                  <td className={td}>
                    {h.kind === "credit_sale" ? <Money value={h.amount} tone="neg" sign /> : <Money value={-h.amount} tone="pos" />}
                  </td>
                  <td className={td}>
                    <Money value={h.balance_after} className="font-semibold" />
                  </td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>

      <PaymentModal
        customer={paying ? { id: data.customer.id, name: data.customer.name, outstanding: b.outstanding } : null}
        onClose={() => setPaying(false)}
        onSaved={reload}
      />
    </>
  );
}

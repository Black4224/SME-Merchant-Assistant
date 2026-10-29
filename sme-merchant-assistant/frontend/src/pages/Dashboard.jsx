import { ArrowDownLeft, ArrowUpRight, Minus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/endpoints";
import { TrendChart } from "../components/Charts";
import { PageHeader } from "../components/Layout";
import { Money } from "../components/Money";
import { PeriodPicker, selToQuery } from "../components/PeriodPicker";
import { FlagBadges, MethodBadge, TypeBadge, partyName } from "../components/txn";
import { Badge, Card, EmptyState, ErrorBanner, Skeleton, TableWrap, cx, td, th } from "../components/ui";
import { fmtDate, fmtDateShort, fmtPct, fmtRange } from "../lib/format";
import { useAsync } from "../lib/useAsync";
function Kpi({ label, value, tone, sub, badge, to }) {
  const body = (
    <div className="h-full rounded-panel border border-line bg-surface p-4 transition-colors sm:p-5 hover:border-line-strong">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-muted">{label}</p>
        {badge}
      </div>
      <p className="mt-2 text-[1.65rem] font-bold leading-tight">
        <Money value={value} tone={tone ?? "none"} />
      </p>
      {sub && <p className="mt-1.5 text-sm text-muted">{sub}</p>}
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-panel">
      {body}
    </Link>
  ) : (
    body
  );
}
function Delta({ change, pct, goodWhenUp = true }) {
  if (change === 0)
    return (
      <span className="inline-flex items-center gap-1 text-sm text-muted">
        <Minus className="size-3.5" aria-hidden />
        بدون تغيير
      </span>
    );
  const good = change > 0 === goodWhenUp;
  const Icon = change > 0 ? ArrowUpRight : ArrowDownLeft;
  return (
    <span className={cx("inline-flex items-center gap-1 text-sm font-semibold", good ? "text-pos" : "text-neg")}>
      <Icon className="size-3.5" aria-hidden />
      <span className="num">{fmtPct(pct)}</span>
    </span>
  );
}
function WeeklyPerformance({ cmp }) {
  const rows = [
    { key: "sales_total", label: "المبيعات", goodWhenUp: true },
    { key: "expenses_total", label: "المصاريف التشغيلية", goodWhenUp: false },
    { key: "purchases_total", label: "مشتريات البضاعة", goodWhenUp: false },
    { key: "estimated_profit", label: "الربح التقديري", goodWhenUp: true, estimate: true },
  ];
  return (
    <Card title="أداء الأسبوع" pad={false}>
      <p className="px-4 pt-3 text-sm text-muted sm:px-5">
        {fmtRange(cmp.current.date_range)} مقارنةً بالفترة نفسها من الأسبوع الماضي ({fmtRange(cmp.previous.date_range)}).
      </p>
      <TableWrap>
        <thead>
          <tr>
            <th className={th}>المؤشر</th>
            <th className={th}>هذا الأسبوع</th>
            <th className={th}>الأسبوع الماضي</th>
            <th className={th}>التغير</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const m = cmp.metrics[r.key];
            return (
              <tr key={r.key}>
                <td className={td}>
                  {r.label}
                  {r.estimate && <Badge tone="warn">تقدير</Badge>}
                </td>
                <td className={td}>
                  <Money value={m.current} tone={r.estimate ? "auto" : "none"} />
                </td>
                <td className={td}>
                  <Money value={m.previous} tone={r.estimate ? "auto" : "none"} />
                </td>
                <td className={td}>
                  <Delta change={m.change} pct={m.pct_change} goodWhenUp={r.goodWhenUp} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </TableWrap>
      {cmp.length_warning && <p className="px-4 pb-3 text-sm text-muted sm:px-5">{cmp.length_warning}</p>}
    </Card>
  );
}
function Attention({ a }) {
  const nothing = !a.overdue_customers.length && !a.top_flags.length && a.unreconciled_count === 0;
  return (
    <Card title="يحتاج انتباهك">
      {nothing ? (
        <EmptyState title="لا توجد عناصر تحتاج مراجعة حالياً" />
      ) : (
        <div className="space-y-5">
          {a.overdue_customers.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-bold text-neg">زبائن متأخرون عن السداد</h3>
              <ul className="divide-y divide-line">
                {a.overdue_customers.map((c) => (
                  <li key={c.customer_id} className="flex items-center justify-between gap-3 py-2">
                    <Link to={`/customers/${c.customer_id}`} className="min-w-0 font-semibold hover:underline">
                      {c.name}
                      {c.oldest_unpaid_date && (
                        <span className="block text-xs font-normal text-muted">أقدم فاتورة غير مسددة: {fmtDate(c.oldest_unpaid_date)}</span>
                      )}
                    </Link>
                    <Money value={c.overdue_amount} tone="neg" className="font-bold" />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {a.top_flags.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-bold">معاملات مشبوهة</h3>
              <ul className="space-y-2">
                {a.top_flags.slice(0, 5).map((f) => (
                  <li key={`${f.transaction_id}-${f.code}`} className="rounded-control border border-line p-2.5 text-sm">
                    <FlagBadges flags={[f]} />
                    <p className="mt-1 text-muted">{f.message_ar}</p>
                    <p className="text-xs text-faint">
                      معاملة رقم <span className="num">{f.transaction_id}</span>
                    </p>
                  </li>
                ))}
              </ul>
              <Link to="/reports?tab=review" className="mt-2 inline-block text-sm font-semibold text-info hover:underline">
                عرض تقرير المراجعة كاملاً
              </Link>
            </div>
          )}
          {a.unreconciled_count > 0 && (
            <p className="text-sm">
              <Link to="/transactions?status=unreconciled" className="font-semibold text-info hover:underline">
                <span className="num">{a.unreconciled_count}</span> معاملة غير مطابقة
              </Link>{" "}
              بانتظار المراجعة.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
export function Dashboard() {
  const [sel, setSel] = useState({ period: "this_month" });
  const { data, error, loading, reload } = useAsync(() => api.dashboard(selToQuery(sel)), [JSON.stringify(sel)]);
  return (
    <>
      <PageHeader
        title="لوحة التحكم"
        subtitle={
          data && (
            <>
              الفترة: {fmtRange(data.period)}
              {data.business.is_demo_data && (
                <span className="block">تاريخ اليوم في البيانات التجريبية: {fmtDate(data.reference_date)}</span>
              )}
            </>
          )
        }
        actions={<PeriodPicker value={sel} onChange={setSel} currentRange={data?.period} />}
      />
      {error && <ErrorBanner error={error} onRetry={reload} />}
      {!data && loading && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}
      {data && (
        <div className={cx("space-y-5", loading && "opacity-60 transition-opacity")} aria-busy={loading}>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi label="مبيعات اليوم" value={data.today.sales_total} sub={`${data.today.transaction_counts.sale ?? 0} عملية بيع`} />
            <Kpi
              label="مصاريف اليوم"
              value={data.today.expenses_total}
              sub={
                data.today.purchases_total > 0 ? (
                  <>
                    مشتريات بضاعة اليوم: <Money value={data.today.purchases_total} />
                  </>
                ) : (
                  "مصاريف تشغيلية فقط"
                )
              }
            />
            <Kpi
              label="صافي الربح التقديري للفترة"
              value={data.period_summary.estimated_profit}
              tone="auto"
              badge={
                <Badge tone="warn" title={data.period_summary.profit_note}>
                  تقدير
                </Badge>
              }
              sub={
                <>
                  صافي النقد: <Money value={data.period_summary.net_cash_flow} tone="auto" />
                </>
              }
            />
            <Kpi
              label="ديون الزبائن المستحقة"
              value={data.outstanding_debts.total}
              to="/customers"
              sub={
                <>
                  <span className="num">{data.outstanding_debts.customers_count}</span> زبون، منها متأخر{" "}
                  <Money value={data.outstanding_debts.overdue_total} tone="neg" />
                </>
              }
            />
          </div>

          <Card
            title="المبيعات والمصاريف يومياً"
            actions={
              <span className="text-sm text-muted">
                {fmtDateShort(data.period.start)} – {fmtDateShort(data.period.end)}
              </span>
            }
          >
            <TrendChart data={data.chart} />
            <dl className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-3" aria-label="إجماليات الفترة">
              <div>
                <dt className="text-sm text-muted">مبيعات الفترة</dt>
                <dd className="font-bold">
                  <Money value={data.period_summary.sales_total} />
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted">المصاريف التشغيلية</dt>
                <dd className="font-bold">
                  <Money value={data.period_summary.expenses_total} />
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted">مشتريات البضاعة</dt>
                <dd className="font-bold">
                  <Money value={data.period_summary.purchases_total} />
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-xs text-muted">{data.period_summary.profit_note}</p>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <WeeklyPerformance cmp={data.weekly_performance} />
            <Attention a={data.attention} />
          </div>

          <Card
            title="آخر المعاملات"
            pad={false}
            actions={
              <Link to="/transactions" className="text-sm font-semibold text-info hover:underline">
                عرض الكل
              </Link>
            }
          >
            {data.recent_transactions.length === 0 ? (
              <EmptyState title="لا توجد معاملات بعد" hint="أضف معاملة أو استورد ملف CSV من صفحة المعاملات." />
            ) : (
              <TableWrap>
                <thead>
                  <tr>
                    <th className={th}>التاريخ</th>
                    <th className={th}>النوع</th>
                    <th className={th}>الوصف</th>
                    <th className={th}>الطرف</th>
                    <th className={th}>الدفع</th>
                    <th className={th}>المبلغ</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_transactions.map((t) => (
                    <tr key={t.id}>
                      <td className={td}>{fmtDateShort(t.date)}</td>
                      <td className={td}>
                        <TypeBadge type={t.type} />
                      </td>
                      <td className={td}>
                        {t.description} <FlagBadges flags={t.flags} />
                      </td>
                      <td className={td}>{partyName(t)}</td>
                      <td className={td}>
                        <MethodBadge method={t.payment_method} />
                      </td>
                      <td className={td}>
                        <Money value={t.amount_iqd} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

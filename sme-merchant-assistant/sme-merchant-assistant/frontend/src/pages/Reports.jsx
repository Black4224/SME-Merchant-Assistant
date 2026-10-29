import { Info } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/endpoints";
import { CumulativeChart, TrendChart } from "../components/Charts";
import { PageHeader } from "../components/Layout";
import { Money } from "../components/Money";
import { PeriodPicker, selToQuery } from "../components/PeriodPicker";
import { FlagBadges, TypeBadge } from "../components/txn";
import { Badge, Card, EmptyState, ErrorBanner, Segmented, Spinner, TableWrap, cx, td, th } from "../components/ui";
import { fmtDate, fmtDateShort, fmtRange } from "../lib/format";
import { FLAG_LABEL } from "../lib/labels";
import { useAsync } from "../lib/useAsync";
const TABS = [
  { value: "summary", label: "الملخص والاتجاهات" },
  { value: "debts", label: "ديون الزبائن" },
  { value: "review", label: "مراجعة المعاملات" },
  { value: "cashflow", label: "التدفق النقدي المتوقع" },
];
const Stat = ({ label, children, note }) => (
  <div className="rounded-panel border border-line bg-surface p-4">
    <p className="flex items-center gap-2 text-sm font-semibold text-muted">
      {label}
      {note}
    </p>
    <p className="mt-1 text-xl font-bold">{children}</p>
  </div>
);
function Summary() {
  const [sel, setSel] = useState({ period: "last_30_days" });
  const [gran, setGran] = useState("weekly");
  const { data, error, loading, reload } = useAsync(
    () => api.reportsSummary({ ...selToQuery(sel), granularity: gran }),
    [JSON.stringify(sel), gran],
  );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PeriodPicker
          value={sel}
          onChange={setSel}
          currentRange={data?.period}
          options={["this_week", "last_week", "this_month", "last_month", "last_7_days", "last_30_days"]}
        />
        <Segmented
          label="مستوى التجميع"
          value={gran}
          onChange={setGran}
          options={[
            { value: "daily", label: "يومي" },
            { value: "weekly", label: "أسبوعي" },
            { value: "monthly", label: "شهري" },
          ]}
        />
      </div>
      {error && <ErrorBanner error={error} onRetry={reload} />}
      {!data ? (
        loading && <Spinner />
      ) : (
        <div className={cx("space-y-5", loading && "opacity-60 transition-opacity")}>
          <p className="text-sm text-muted">
            الفترة: {fmtRange(data.period)} ({data.period.days} يوماً)
          </p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <Stat label="إجمالي المبيعات">
              <Money value={data.totals.sales_total} />
            </Stat>
            <Stat label="منها آجل (غير مقبوض)">
              <Money value={data.totals.sales_credit} />
            </Stat>
            <Stat label="تسديدات الزبائن (ليست مبيعات)">
              <Money value={data.totals.customer_payments} tone="pos" />
            </Stat>
            <Stat label="المصاريف التشغيلية">
              <Money value={data.totals.expenses_total} />
            </Stat>
            <Stat label="مشتريات البضاعة">
              <Money value={data.totals.purchases_total} />
            </Stat>
            <Stat
              label="الربح التقديري"
              note={
                <Badge tone="warn" title={data.totals.profit_note}>
                  تقدير
                </Badge>
              }
            >
              <Money value={data.totals.estimated_profit} tone="auto" />
            </Stat>
            <Stat label="صافي النقد (مقبوض − مدفوع)">
              <Money value={data.totals.net_cash_flow} tone="auto" />
            </Stat>
          </div>
          <Card title="الاتجاه عبر الفترة">
            <TrendChart
              showProfit
              data={data.series.map((b) => ({
                date: b.start,
                sales: b.sales,
                expenses: b.expenses,
                purchases: b.purchases,
                estimated_profit: b.estimated_profit,
              }))}
            />
          </Card>
          <Card title="التفاصيل" pad={false}>
            <TableWrap>
              <thead>
                <tr>
                  <th className={th}>الفترة</th>
                  <th className={th}>المبيعات</th>
                  <th className={th}>المصاريف</th>
                  <th className={th}>مشتريات البضاعة</th>
                  <th className={th}>الربح التقديري</th>
                  <th className={th}>صافي النقد</th>
                </tr>
              </thead>
              <tbody>
                {[...data.series].reverse().map((b) => (
                  <tr key={b.start}>
                    <td className={td}>
                      {b.start === b.end ? fmtDateShort(b.start) : `${fmtDateShort(b.start)} – ${fmtDateShort(b.end)}`}
                    </td>
                    <td className={td}>
                      <Money value={b.sales} />
                    </td>
                    <td className={td}>
                      <Money value={b.expenses} />
                    </td>
                    <td className={td}>
                      <Money value={b.purchases} />
                    </td>
                    <td className={td}>
                      <Money value={b.estimated_profit} tone="auto" />
                    </td>
                    <td className={td}>
                      <Money value={b.net_cash_flow} tone="auto" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          </Card>
          <p className="flex items-start gap-2 rounded-control bg-warn-bg px-3 py-2 text-sm text-warn">
            <Info className="mt-1 size-4 shrink-0" aria-hidden />
            {data.estimate_note}
          </p>
        </div>
      )}
    </div>
  );
}
function Debts() {
  const { data, error, reload } = useAsync(() => api.debtsReport(), []);
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="إجمالي الديون">
          <Money value={data.total_outstanding} />
        </Stat>
        <Stat label={`المتأخر (أكثر من ${data.credit_terms_days} يوماً)`}>
          <Money value={data.total_overdue} tone={data.total_overdue > 0 ? "neg" : "none"} />
        </Stat>
        <Stat label="عدد الزبائن المدينين">
          <span className="num">{data.customers.length}</span>
        </Stat>
      </div>
      <Card title="تقرير ديون الزبائن" pad={false}>
        {data.customers.length === 0 ? (
          <EmptyState title="لا توجد ديون مستحقة" />
        ) : (
          <TableWrap>
            <thead>
              <tr>
                <th className={th}>الزبون</th>
                <th className={th}>المستحق</th>
                <th className={th}>المتأخر</th>
                <th className={th}>أقدم فاتورة غير مسددة</th>
                <th className={th}>آخر دفعة</th>
                <th className={th}>فواتير مفتوحة</th>
              </tr>
            </thead>
            <tbody>
              {data.customers.map((c) => (
                <tr key={c.customer_id}>
                  <td className={td}>
                    <Link className="font-semibold hover:underline" to={`/customers/${c.customer_id}`}>
                      {c.name}
                    </Link>
                  </td>
                  <td className={td}>
                    <Money value={c.outstanding} className="font-bold" tone="neg" />
                  </td>
                  <td className={td}>
                    {c.overdue_amount > 0 ? <Money value={c.overdue_amount} tone="neg" /> : <span className="text-faint">—</span>}
                  </td>
                  <td className={td}>{fmtDate(c.oldest_unpaid_date)}</td>
                  <td className={td}>{fmtDate(c.last_payment_date)}</td>
                  <td className={td}>
                    <span className="num">{c.open_invoices.length}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Card>
      <p className="text-xs text-muted">
        الدين = مبيعات آجلة − تسديدات. الدفعات تُوزَّع على أقدم فاتورة أولاً. الحساب حتى {fmtDate(data.as_of)}.
      </p>
    </div>
  );
}
function Review() {
  const { data, error, reload } = useAsync(() => api.anomaliesReport(), []);
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">
          المجموع: <span className="num">{data.count}</span> تنبيه
        </span>
        {Object.entries(data.by_code).map(([code, n]) => (
          <Badge key={code}>
            {FLAG_LABEL[code] ?? code}: <span className="num">{n}</span>
          </Badge>
        ))}
      </div>
      <p className="text-sm text-muted">
        هذه تنبيهات للمراجعة وليست حكماً نهائياً. المعاملة المُنبَّه عليها تبقى محسوبة في الأرقام حتى تستبعدها أو تعدّلها من صفحة المعاملات.
      </p>
      <Card pad={false}>
        {data.items.length === 0 ? (
          <EmptyState title="لا توجد معاملات تحتاج مراجعة" />
        ) : (
          <ul className="divide-y divide-line">
            {data.items.map((it) => (
              <li key={`${it.transaction_id}-${it.code}`} className="space-y-1.5 px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-center gap-2">
                  <FlagBadges flags={[it]} />
                  <TypeBadge type={it.transaction.type} />
                  <span className="text-sm text-muted">{fmtDate(it.transaction.date)}</span>
                  <Money value={it.transaction.amount_iqd} className="font-semibold" />
                  <span className="text-xs text-faint">
                    معاملة <span className="num">#{it.transaction_id}</span>
                  </span>
                </div>
                <p className="text-sm">{it.transaction.description}</p>
                <p className="text-sm text-muted">{it.message_ar}</p>
                {it.related_ids.length > 0 && (
                  <p className="text-xs text-muted">
                    مرتبطة بالمعاملة: <span className="num">{it.related_ids.map((i) => `#${i}`).join("، ")}</span>
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Link to="/transactions?status=unreconciled" className="inline-block text-sm font-semibold text-info hover:underline">
        عرض المعاملات غير المطابقة في صفحة المعاملات
      </Link>
    </div>
  );
}
function Cashflow() {
  const { data, error, reload } = useAsync(() => api.cashflow(30), []);
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  return (
    <div className="space-y-5">
      <div role="note" className="flex items-start gap-3 rounded-panel border border-[#efd8ab] bg-warn-bg px-4 py-3 text-warn">
        <Info className="mt-1 size-5 shrink-0" aria-hidden />
        <div>
          <p className="font-bold">هذا تقدير وليس ضماناً</p>
          <p className="text-sm leading-7">{data.disclaimer_ar}</p>
        </div>
      </div>
      {!data.sufficient_data ? (
        <Card>
          <EmptyState title="لا توجد بيانات كافية للتوقع" hint={data.note_ar} />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <Stat label={`التغير المتوقع في النقد خلال ${data.horizon_days} يوماً`} note={<Badge tone="warn">تقدير</Badge>}>
              <Money value={data.projected_net_change} tone="auto" />
            </Stat>
            <Stat label="المدى التقريبي">
              <span className="text-base">
                <Money value={data.low} tone="auto" /> إلى <Money value={data.high} tone="auto" />
              </span>
            </Stat>
            <Stat label="متوسط المقبوض / المدفوع يومياً">
              <span className="text-base">
                <Money value={data.avg_daily_cash_in ?? 0} tone="pos" /> / <Money value={data.avg_daily_cash_out ?? 0} />
              </span>
            </Stat>
          </div>
          <Card title="تقدير صافي النقد التراكمي">
            <CumulativeChart points={data.checkpoints.map((c) => ({ day: c.day, cumulative: c.cumulative_net }))} />
          </Card>
        </>
      )}
      <Card title="ديون الزبائن">
        <p className="text-lg font-bold">
          <Money value={data.outstanding_receivables} />
        </p>
        <p className="mt-1 text-sm text-muted">{data.receivables_note_ar}</p>
      </Card>
      <p className="text-sm text-muted">
        طريقة الحساب: متوسط صافي النقد اليومي خلال الفترة من {fmtDate(data.lookback.start)} إلى {fmtDate(data.lookback.end)}، مضروباً في عدد
        أيام التوقع. المدى يعكس تذبذب الأسابيع السابقة وليس فاصل ثقة إحصائياً. الرقم هو تغيّر في النقد وليس رصيد الصندوق.
      </p>
    </div>
  );
}
export function Reports() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.value === params.get("tab")) ? params.get("tab") : "summary";
  return (
    <>
      <PageHeader title="التقارير" />
      <div className="overflow-x-auto">
        <Segmented label="أقسام التقارير" value={tab} options={TABS} onChange={(v) => setParams({ tab: v }, { replace: true })} />
      </div>
      {tab === "summary" && <Summary />}
      {tab === "debts" && <Debts />}
      {tab === "review" && <Review />}
      {tab === "cashflow" && <Cashflow />}
    </>
  );
}

import { FileSearch, Info } from "lucide-react";
import { Fragment } from "react";
import { MINUS, fmtDateShort, fmtRange } from "../lib/format";
import { Money } from "./Money";
import { FlagBadges, MethodBadge, TypeBadge, partyName } from "./txn";
import { Badge, cx } from "./ui";
const TOKEN = /(\d{4}-\d{2}-\d{2}|[-\u2212]?\d[\d,.]*%?)/g;
const MONEY_ONLY = /^[-\u2212]?[\d,]+ د\.ع$/;
/** Backend strings mix Arabic words and numbers ("-1,500 د.ع"). Isolate every number LTR and use a real minus sign. */
export function Mixed({ text }) {
  const s = String(text);
  if (MONEY_ONLY.test(s)) {
    const v = Number(s.replace(/[^\d-\u2212]/g, "").replace(MINUS, "-"));
    return <Money value={v} />;
  }
  return (
    <>
      {s.split(TOKEN).map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} className="num">
            {part.replace(/^-/, MINUS)}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
export function EvidenceView({ ev }) {
  const shown = ev.transactions.length;
  const total = ev.transaction_ids.length;
  return (
    <article className="rounded-panel border border-line bg-surface" aria-label={`الدليل: ${ev.title_ar}`}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-page/60 px-4 py-2.5">
        <h3 className="flex items-center gap-2 font-bold">
          <FileSearch className="size-4 text-info" aria-hidden />
          {ev.title_ar}
        </h3>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
          {ev.is_estimate && <Badge tone="warn">تقدير</Badge>}
          {ev.date_range && <span>{fmtRange(ev.date_range)}</span>}
          {ev.secondary_range && <span>مقارنة مع {fmtRange(ev.secondary_range)}</span>}
        </div>
      </header>

      <div className="space-y-4 p-4">
        {!ev.has_data && <p className="rounded-control bg-page px-3 py-2 text-sm text-muted">لا توجد بيانات كافية لهذا السؤال.</p>}

        {ev.figures.length > 0 && (
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {ev.figures.map((f) => (
              <div key={f.key}>
                <dt className="text-xs text-muted">{f.label_ar}</dt>
                <dd className="text-base font-bold">
                  <Mixed text={f.display} />
                </dd>
              </div>
            ))}
          </dl>
        )}

        {ev.table.rows.length > 0 && (
          <div className="overflow-x-auto rounded-control border border-line">
            <table className="w-full min-w-[480px] border-collapse text-sm">
              <thead>
                <tr>
                  {ev.table.columns.map((c) => (
                    <th key={c.key} className="border-b border-line bg-page px-3 py-2 text-start text-xs font-semibold text-muted">
                      {c.label_ar}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ev.table.rows.map((r, i) => (
                  <tr key={i}>
                    {ev.table.columns.map((c) => (
                      <td key={c.key} className="border-b border-line px-3 py-2 last:border-b-0">
                        {r[c.key] === undefined || r[c.key] === "" ? "—" : <Mixed text={r[c.key]} />}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {ev.warnings.map((w, i) => (
          <p key={i} className="flex items-start gap-2 rounded-control border border-[#efd8ab] bg-warn-bg px-3 py-2 text-sm text-warn">
            <Info className="mt-1 size-4 shrink-0" aria-hidden />
            {w}
          </p>
        ))}

        <p className="text-sm text-muted">
          <span className="font-semibold text-ink">أساس الحساب: </span>
          {ev.basis_ar}
        </p>

        {ev.evidence_kind === "aggregate" ? (
          <p className="text-sm text-muted">هذا الرقم مبني على متوسط نشاط الأسابيع الماضية، لذلك لا توجد معاملات مفردة تثبته.</p>
        ) : (
          total > 0 && (
            <details className="group rounded-control border border-line">
              <summary className="cursor-pointer select-none px-3 py-2.5 text-sm font-semibold hover:bg-page">
                المعاملات الداعمة (<span className="num">{total}</span>)
              </summary>
              <div className="space-y-3 border-t border-line p-3">
                {Object.entries(ev.id_groups)
                  .filter(([, ids]) => ids.length)
                  .map(([group, ids]) => (
                    <p key={group} className="text-xs leading-6 text-muted">
                      <span className="font-semibold text-ink">
                        {GROUP_LABEL[group] ?? group} (<span className="num">{ids.length}</span>):{" "}
                      </span>
                      <span className="num break-words">
                        {ids.slice(0, 40).join("، ")}
                        {ids.length > 40 ? " …" : ""}
                      </span>
                    </p>
                  ))}
                {ev.ids_truncated && <p className="text-xs text-warn">القائمة مقصوصة لطولها.</p>}
                {shown > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[520px] border-collapse text-sm">
                      <thead>
                        <tr>
                          {["رقم", "التاريخ", "النوع", "الطرف", "الدفع", "المبلغ"].map((h) => (
                            <th key={h} className="border-b border-line px-2 py-1.5 text-start text-xs font-semibold text-muted">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {ev.transactions.map((t) => (
                          <tr key={t.id} className={cx(t.flags.length > 0 && "bg-warn-bg/40")}>
                            <td className="border-b border-line px-2 py-1.5">
                              <span className="num">{t.id}</span>
                            </td>
                            <td className="border-b border-line px-2 py-1.5">{fmtDateShort(t.date)}</td>
                            <td className="border-b border-line px-2 py-1.5">
                              <TypeBadge type={t.type} /> <FlagBadges flags={t.flags} />
                            </td>
                            <td className="border-b border-line px-2 py-1.5">{partyName(t)}</td>
                            <td className="border-b border-line px-2 py-1.5">
                              <MethodBadge method={t.payment_method} />
                            </td>
                            <td className="border-b border-line px-2 py-1.5">
                              <Money value={t.amount_iqd} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {total > shown && (
                      <p className="mt-2 text-xs text-muted">
                        معروض <span className="num">{shown}</span> من أصل <span className="num">{total}</span> معاملة. الأرقام الكاملة
                        مذكورة أعلاه.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </details>
          )
        )}
      </div>
    </article>
  );
}
const GROUP_LABEL = {
  sale: "المبيعات",
  expense: "المصاريف",
  supplier_purchase: "مشتريات البضاعة",
  supplier_payment: "تسديدات الموردين",
  customer_payment: "تسديدات الزبائن",
  open_credit_sales: "فواتير آجلة غير مسددة",
  flagged: "معاملات للمراجعة",
  recent: "آخر المعاملات",
  current_sale: "مبيعات الفترة الحالية",
  previous_sale: "مبيعات الفترة السابقة",
  current_expense: "مصاريف الفترة الحالية",
  previous_expense: "مصاريف الفترة السابقة",
  current_supplier_purchase: "مشتريات الفترة الحالية",
  previous_supplier_purchase: "مشتريات الفترة السابقة",
};

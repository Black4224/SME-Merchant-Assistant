import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtDateShort, fmtIqd } from "../lib/format";
export const COLORS = { sales: "#0e8a5f", expenses: "#8793a5", purchases: "#d49a2a", profit: "#0f1f3d", neg: "#c4312c" };
const compact = new Intl.NumberFormat("ar-IQ-u-nu-latn", { notation: "compact", maximumFractionDigits: 1 });
const SERIES_LABEL = {
  sales: "المبيعات",
  expenses: "المصاريف التشغيلية",
  purchases: "مشتريات البضاعة",
  estimated_profit: "الربح التقديري (تقدير)",
  cumulative: "صافي النقد التراكمي (تقدير)",
};
function Tip({ active, payload, label, labelFmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div dir="rtl" className="rounded-control border border-line bg-surface px-3 py-2 text-sm shadow-lg">
      <p className="mb-1 font-bold">{labelFmt ? labelFmt(label) : label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm" style={{ background: p.color ?? p.fill }} />
            {SERIES_LABEL[p.dataKey] ?? p.name}
          </span>
          <span className="num font-semibold">{fmtIqd(p.value)}</span>
        </p>
      ))}
    </div>
  );
}
/** Time runs right-to-left (axis reversed, value axis on the right) to match Arabic reading direction. */
export function TrendChart({ data, showProfit = false, height = 300 }) {
  return (
    <div style={{ height }} role="img" aria-label="رسم بياني للمبيعات والمصاريف عبر الزمن">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, left: 4, bottom: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke="#e2e7ef" />
          <XAxis
            dataKey="date"
            reversed
            tickFormatter={fmtDateShort}
            tick={{ fontSize: 12, fill: "#5a6678" }}
            tickLine={false}
            axisLine={{ stroke: "#cbd3df" }}
            minTickGap={24}
          />
          <YAxis
            orientation="right"
            tickFormatter={(v) => compact.format(v)}
            tick={{ fontSize: 12, fill: "#5a6678" }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip content={<Tip labelFmt={fmtDateShort} />} cursor={{ fill: "#f0f3f8" }} isAnimationActive={false} />
          <Legend formatter={(v) => SERIES_LABEL[v] ?? v} wrapperStyle={{ fontSize: 13, paddingTop: 8 }} />
          <Bar dataKey="sales" fill={COLORS.sales} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="expenses" fill={COLORS.expenses} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="purchases" fill={COLORS.purchases} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          {showProfit && (
            <Line
              dataKey="estimated_profit"
              stroke={COLORS.profit}
              strokeWidth={2.5}
              dot={{ r: 3 }}
              strokeDasharray="6 3"
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
export function CumulativeChart({ points }) {
  const data = [{ day: 0, cumulative: 0 }, ...points];
  return (
    <div style={{ height: 220 }} role="img" aria-label="تقدير صافي النقد التراكمي">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="#e2e7ef" />
          <XAxis
            dataKey="day"
            reversed
            tickFormatter={(d) => (d === 0 ? "اليوم" : `+${d}`)}
            tick={{ fontSize: 12, fill: "#5a6678" }}
            tickLine={false}
          />
          <YAxis
            orientation="right"
            tickFormatter={(v) => compact.format(v)}
            tick={{ fontSize: 12, fill: "#5a6678" }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <ReferenceLine y={0} stroke="#cbd3df" />
          <Tooltip content={<Tip labelFmt={(d) => (d === 0 ? "اليوم" : `بعد ${d} يوماً`)} />} isAnimationActive={false} />
          <Line
            dataKey="cumulative"
            stroke={COLORS.profit}
            strokeWidth={2.5}
            strokeDasharray="6 3"
            dot={{ r: 3 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

import { useState } from "react";
import { PERIOD_LABEL } from "../lib/labels";
import { inputCls } from "./ui";
export const selToQuery = (s) => ("period" in s ? { period: s.period } : { start: s.start, end: s.end });
const DEFAULT_OPTIONS = ["today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_7_days", "last_30_days"];
/** `currentRange` (the range the page is showing now) pre-fills the custom dates so switching never fires an empty query. */
export function PeriodPicker({ value, onChange, currentRange, options = DEFAULT_OPTIONS, label = "الفترة" }) {
  const [custom, setCustom] = useState("start" in value);
  const [draft, setDraft] = useState({ start: "start" in value ? value.start : "", end: "start" in value ? value.end : "" });
  const invalid = !!draft.start && !!draft.end && draft.start > draft.end;
  const setDates = (next) => {
    setDraft(next);
    if (next.start && next.end && next.start <= next.end) onChange(next);
  };
  const choose = (v) => {
    if (v === "custom") {
      setCustom(true);
      if (currentRange) setDates({ start: currentRange.start, end: currentRange.end });
    } else {
      setCustom(false);
      onChange({ period: v });
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-muted">{label}</span>
        <select
          aria-label="الفترة"
          className={inputCls() + " w-auto min-w-40"}
          value={custom ? "custom" : "period" in value ? value.period : "this_month"}
          onChange={(e) => choose(e.target.value)}
        >
          {options.map((p) => (
            <option key={p} value={p}>
              {PERIOD_LABEL[p]}
            </option>
          ))}
          <option value="custom">فترة مخصصة…</option>
        </select>
      </label>
      {custom && (
        <>
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-muted">من</span>
            <input
              type="date"
              className={inputCls(invalid) + " w-auto"}
              value={draft.start}
              onChange={(e) => setDates({ ...draft, start: e.target.value })}
            />
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-muted">إلى</span>
            <input
              type="date"
              className={inputCls(invalid) + " w-auto"}
              value={draft.end}
              onChange={(e) => setDates({ ...draft, end: e.target.value })}
            />
          </label>
          {invalid && (
            <p role="alert" className="text-sm text-neg">
              تاريخ البداية بعد تاريخ النهاية
            </p>
          )}
        </>
      )}
    </div>
  );
}

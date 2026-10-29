const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹";
const LATIN_DIGITS = "01234567890123456789";
export const MINUS = "\u2212";
export function fmtNum(n) {
  return `${n < 0 ? MINUS : ""}${Math.abs(Math.trunc(n)).toLocaleString("en-US")}`;
}
/** Plain-text money (tooltips, aria labels). Visual UI uses <Money/>, which isolates the number's direction. */
export function fmtIqd(n, currency = "د.ع") {
  return `${fmtNum(n)} ${currency}`;
}
const DATE_FMT = new Intl.DateTimeFormat("ar-IQ-u-nu-latn-ca-gregory", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const DATE_SHORT = new Intl.DateTimeFormat("ar-IQ-u-nu-latn-ca-gregory", { day: "numeric", month: "short", timeZone: "UTC" });
function parseIso(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
}
export const fmtDate = (iso) => (iso && parseIso(iso) ? DATE_FMT.format(parseIso(iso)) : "—");
export const fmtDateShort = (iso) => (iso && parseIso(iso) ? DATE_SHORT.format(parseIso(iso)) : "—");
export const fmtRange = (r) => (!r ? "" : r.start === r.end ? fmtDate(r.start) : `${fmtDate(r.start)} – ${fmtDate(r.end)}`);
export const fmtPct = (p) =>
  p === null || p === undefined ? "غير محسوب" : `${Number(p) > 0 ? "+" : Number(p) < 0 ? MINUS : ""}${Math.abs(Number(p))}%`;
/** Mirrors backend parse_amount: whole positive dinars; accepts Arabic digits and separators. null = invalid. */
export function parseAmountInput(text) {
  let t = text.trim();
  if (!t) return null;
  t = [...t]
    .map((c) => {
      const i = ARABIC_DIGITS.indexOf(c);
      return i >= 0 ? LATIN_DIGITS[i] : c;
    })
    .join("");
  t = t
    .replace(/[,\u066c\s_\u00a0]/g, "")
    .replace(/\u066b/g, ".")
    .replace(/د\.ع|IQD/gi, "");
  if (!/^\d+(\.0+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isSafeInteger(n) && n > 0 && n <= 100_000_000_000 ? n : null;
}
export const todayIso = () => new Date().toISOString().slice(0, 10);

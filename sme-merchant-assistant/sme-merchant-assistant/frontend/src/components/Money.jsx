import { fmtNum } from "../lib/format";
import { useSettings } from "../lib/settings";
import { cx } from "./ui";
/** Money with the number isolated left-to-right so minus signs and commas never flip inside Arabic text. */
export function Money({ value, tone = "none", sign = false, unit = true, className }) {
  const { currency } = useSettings();
  const color =
    tone === "auto"
      ? value > 0
        ? "text-pos"
        : value < 0
          ? "text-neg"
          : ""
      : tone === "pos"
        ? "text-pos"
        : tone === "neg"
          ? "text-neg"
          : "";
  const text = `${sign && value > 0 ? "+" : ""}${fmtNum(value)}`;
  return (
    <span className={cx("whitespace-nowrap", color, className)}>
      <span className="num">{text}</span>
      {unit && <span className="ms-1 text-[0.85em] font-medium opacity-80">{currency}</span>}
    </span>
  );
}

import { AlertTriangle } from "lucide-react";
import { FLAG_LABEL, METHOD_LABEL, SEVERITY_LABEL, TYPE_LABEL } from "../lib/labels";
import { Badge } from "./ui";
const TYPE_TONE = {
  sale: "info",
  customer_payment: "pos",
  expense: "neutral",
  supplier_purchase: "warn",
  supplier_payment: "neutral",
};
export const TypeBadge = ({ type }) => <Badge tone={TYPE_TONE[type]}>{TYPE_LABEL[type]}</Badge>;
export const MethodBadge = ({ method }) =>
  method === "credit" ? <Badge tone="warn">آجل</Badge> : <span className="text-muted">{METHOD_LABEL[method]}</span>;
export const partyName = (t) => t.customer?.name ?? t.supplier?.name ?? "—";
export function FlagBadges({ flags }) {
  if (!flags.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((f) => (
        <Badge
          key={f.code}
          tone={f.severity === "high" ? "neg" : f.severity === "medium" ? "warn" : "neutral"}
          title={`${f.message_ar} (أهمية ${SEVERITY_LABEL[f.severity]})`}
        >
          <AlertTriangle className="size-3" aria-hidden />
          {FLAG_LABEL[f.code] ?? f.code}
        </Badge>
      ))}
    </span>
  );
}

"""Structured output of every tool: figures + evidence. Built ONLY from deterministic services."""
import json
from dataclasses import dataclass, field
from typing import Any

MAX_UI_TRANSACTIONS = 25
MAX_MODEL_ROWS = 15
MAX_MODEL_IDS = 15
MAX_ID_LIST = 1000


@dataclass
class Figure:
    key: str
    label_ar: str
    value: int | str | None
    display: str

    def to_dict(self) -> dict:
        return {"key": self.key, "label_ar": self.label_ar, "value": self.value, "display": self.display}


@dataclass
class ToolResult:
    tool: str
    arguments: dict
    title_ar: str
    basis_ar: str
    date_range: dict | None = None
    secondary_range: dict | None = None  # e.g. the "previous" period in a comparison
    figures: list[Figure] = field(default_factory=list)
    table_columns: list[dict] = field(default_factory=list)  # [{"key","label_ar"}]
    table_rows: list[dict] = field(default_factory=list)
    id_groups: dict[str, list[int]] = field(default_factory=dict)  # evidence: group -> transaction ids
    transactions: list[dict] = field(default_factory=list)  # serialized, capped
    warnings: list[str] = field(default_factory=list)
    is_estimate: bool = False
    has_data: bool = True
    evidence_kind: str = "transactions"  # "transactions" | "aggregate" (projection - no row-level evidence)
    ids_truncated: bool = False

    @property
    def transaction_ids(self) -> list[int]:
        seen, out = set(), []
        for ids in self.id_groups.values():
            for i in ids:
                if i not in seen:
                    seen.add(i)
                    out.append(i)
        return out

    def to_ui_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "title_ar": self.title_ar,
            "basis_ar": self.basis_ar,
            "date_range": self.date_range,
            "secondary_range": self.secondary_range,
            "figures": [f.to_dict() for f in self.figures],
            "table": {"columns": self.table_columns, "rows": self.table_rows},
            "transaction_ids": self.transaction_ids,
            "id_groups": self.id_groups,
            "ids_truncated": self.ids_truncated,
            "transactions": self.transactions[:MAX_UI_TRANSACTIONS],
            "warnings": self.warnings,
            "is_estimate": self.is_estimate,
            "has_data": self.has_data,
            "evidence_kind": self.evidence_kind,
        }

    def to_model_payload(self) -> dict:
        """What the LLM sees: compact, no free-text descriptions (untrusted user text stays out)."""
        ids = self.transaction_ids
        return {
            "tool": self.tool,
            "title": self.title_ar,
            "calculation_basis": self.basis_ar,
            "date_range": self.date_range,
            "compared_with": self.secondary_range,
            "figures": [{"label": f.label_ar, "value": f.display} for f in self.figures],
            "rows": self.table_rows[:MAX_MODEL_ROWS],
            "rows_total": len(self.table_rows),
            "supporting_transactions_count": len(ids),
            "supporting_transaction_ids_sample": ids[:MAX_MODEL_IDS],
            "warnings": self.warnings,
            "is_estimate": self.is_estimate,
            "has_data": self.has_data,
        }

    def all_numbers_text(self) -> str:
        """Numbers an answer may legitimately quote: figures, table cells, date ranges, call arguments and counts.
        Deliberately EXCLUDES raw transaction-id lists and per-transaction dates, which would make almost any small number 'exist'."""
        blob: dict[str, Any] = {
            "arguments": self.arguments, "title": self.title_ar, "basis": self.basis_ar, "date_range": self.date_range,
            "secondary_range": self.secondary_range, "figures": [{"value": f.value, "display": f.display} for f in self.figures],
            "table": self.table_rows, "warnings": self.warnings, "supporting_transactions_count": len(self.transaction_ids),
        }
        return json.dumps(blob, ensure_ascii=False, default=str)

    def render_plain(self) -> str:
        """Deterministic Arabic text. Used as the fallback answer and as an offline summary."""
        lines = [self.title_ar]
        if self.date_range:
            lines.append(f"الفترة: من {self.date_range['start']} إلى {self.date_range['end']}")
        if self.secondary_range:
            lines.append(f"مقارنة مع: من {self.secondary_range['start']} إلى {self.secondary_range['end']}")
        if not self.has_data:
            lines.append("لا توجد بيانات كافية لهذا السؤال.")
        lines += [f"• {f.label_ar}: {f.display}" for f in self.figures]
        for row in self.table_rows[:5]:
            lines.append("– " + "، ".join(f"{c['label_ar']}: {row.get(c['key'], '')}" for c in self.table_columns))
        if len(self.table_rows) > 5:
            lines.append(f"(+{len(self.table_rows) - 5} صفوف أخرى في الجدول)")
        lines += [f"⚠ {w}" for w in self.warnings]
        lines.append(f"أساس الحساب: {self.basis_ar}")
        return "\n".join(lines)

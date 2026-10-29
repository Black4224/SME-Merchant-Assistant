# REST API (Phases 2–3)

Base URL (dev): `http://localhost:8000`. Interactive docs: `/docs` (Swagger) and `/redoc`.
All money is **integer IQD**. Dates are `YYYY-MM-DD`. All ranges are **inclusive**.
JSON field names are English; user-facing messages are Arabic.

## Errors (uniform)
```json
{"error": {"code": "business_rule", "message": "البيع بالآجل يحتاج إلى زبون", "details": null}}
```
| status | codes |
|---|---|
| 404 | `not_found` |
| 502 | `ai_rate_limit`, `ai_timeout`, `ai_auth`, `ai_connection`, `ai_server`, `ai_bad_request`, `ai_unknown` (provider failed) |
| 503 | `ai_not_configured` (no API key/model set) |
| 409 | `duplicate_name`, `file_already_imported`, `file_changed` |
| 413 | `payload_too_large` (CSV > 5 MB or > 20,000 rows) |
| 422 | `validation_error` (with `details: [{field, message}]`), `business_rule`, `invalid_amount`, `invalid_date_range`, `overpayment`, `invalid_rows`, `mapping_required`, `bad_mapping`, `bad_csv`, `empty_file`, `no_rows`, `bad_encoding`, `confirmation_required` |
| 500 | `internal_error` (no internals leaked) |

## Pagination
List endpoints take `page` (≥1, default 1) and `page_size` (1–200, default 25) and return
`{"items": [...], "total": N, "page": 1, "page_size": 25, "pages": P}`.

## Endpoints
| method | path | purpose |
|---|---|---|
| GET | `/api/health` | liveness, DB check, `ai_configured`, `is_demo_data` |
| GET | `/api/dashboard/summary` | everything the dashboard shows (see below) |
| GET | `/api/transactions` | filtered, sorted, paginated list (rows include anomaly `flags`) |
| POST | `/api/transactions` | create → `201` |
| GET | `/api/transactions/{id}` | one transaction |
| PUT | `/api/transactions/{id}` | full replacement (re-validated) |
| DELETE | `/api/transactions/{id}` | hard delete → `{"deleted": id}` (use `reconciliation_status: "excluded"` to keep but ignore) |
| POST | `/api/import/csv/preview` | multipart; validate + dedupe, **writes nothing** |
| POST | `/api/import/csv/confirm` | multipart; commit valid, non-duplicate rows atomically → `201` |
| GET | `/api/customers` | customers with balances (`q`, `has_debt`, paging) |
| POST | `/api/customers` | create customer |
| GET | `/api/customers/{id}/debts` | balance, open invoices (FIFO), full debt history |
| POST | `/api/customers/{id}/payments` | record a payment → `201` |
| GET/POST | `/api/suppliers` | suppliers with payables / create |
| GET | `/api/categories` | categories |
| GET | `/api/reports/summary` | totals + daily/weekly/monthly series |
| GET | `/api/reports/debts` | customer debt report (outstanding, overdue) |
| GET | `/api/reports/anomalies` | suspicious / unreconciled report with evidence |
| GET | `/api/reports/cashflow` | 30-day projection (**estimate**) |
| GET/PUT | `/api/settings` | business name, currency display, credit terms, AI status, demo flag |
| POST | `/api/settings/reset-demo` | **destructive**; body `{"confirm":"RESET"}` wipes DB and reloads demo data |
| GET | `/api/assistant/status` | `{provider, configured, message_ar}`. `provider: "rules"` = offline keyword mode (`configured: true`, `message_ar` explains the limits) |
| POST | `/api/assistant/chat` | ask a question in Iraqi Arabic → answer + evidence (see below, `docs/ai-architecture.md`) |

### Transactions
`POST/PUT` body:
```json
{"date":"2026-10-10","type":"sale","amount":150000,"description":"بيع نقدي",
 "payment_method":"cash","reference":null,"customer_id":null,"supplier_id":null,
 "category_id":null,"reconciliation_status":null}
```
`amount` may also be text (`"1,250,000"`, `"١٢٥٠٠٠٠"`); floats, booleans, zero, negatives and fractions → `422`.
`type`: `sale|customer_payment|expense|supplier_purchase|supplier_payment`.
`payment_method`: `cash|digital|bank|credit`. Combination rules: see `business-rules.md`. Unknown fields are rejected.

`GET /api/transactions` filters: `q` (description / reference / customer / supplier, Arabic-variant aware),
`type`, `payment_method`, `status`, `customer_id`, `supplier_id`, `category_id`, `date_from`, `date_to`,
`min_amount`, `max_amount`, `sort` (`date|amount|id`), `order` (`asc|desc`).

### Customer payments
`POST /api/customers/{id}/payments` body: `{"amount":500000,"date":null,"payment_method":"cash|digital|bank","description":"…","reference":null,"allow_overpayment":false}`.
Creates a `customer_payment` (never a sale). A payment larger than the debt at that date is refused
(`overpayment`) unless `allow_overpayment` is true. Response: `{transaction, outstanding_before, outstanding_after}`.

### CSV import (two steps, stateless)
1. `POST /api/import/csv/preview` — form fields: `file`, optional `mapping` (JSON `{"date":"التاريخ", ...}`).
   Returns `headers`, `suggested_mapping`, `needs_mapping`, `missing_required_fields`,
   `counts {total, valid, duplicate, invalid}`, `will_create {customers, suppliers, categories}`,
   `rows` (first 200, each `valid|duplicate|invalid` with `warnings`), `errors` (every invalid row with
   `row_number` and per-field messages), `already_imported`, `file_sha256`.
2. `POST /api/import/csv/confirm` — same `file`/`mapping` plus `skip_invalid` (default false) and
   `expected_sha256` (pins the previewed file). Refuses (`422 invalid_rows`) if invalid rows exist and
   `skip_invalid` is false; refuses (`409`) if this exact file was already imported. All-or-nothing.

Accepted: UTF-8 (with/without BOM) or Windows-1256; `,` `;` or tab separators; English or Arabic headers
and values (`بيع`, `آجل`, `نقدي`…); `YYYY-MM-DD` or day-first `DD/MM/YYYY`; Arabic-Indic digits.
Full column spec: `csv-schema.md`.

### Dashboard — `GET /api/dashboard/summary?period=this_month` or `?start=…&end=…`
Returns `business`, `reference_date`, `period`, `today`, `period_summary`, `outstanding_debts {total,
customers_count, overdue_total}`, `recent_transactions` (10), `chart` (one point per day),
`weekly_performance` (this week-to-date vs the same span last week), `attention {unreconciled_count,
flags_by_code, top_flags, overdue_customers}`. `period` ∈ `today, yesterday, this_week, last_week,
this_month, last_month, last_month_same_span, last_7_days, last_30_days`.

### Reports — `GET /api/reports/summary?period=…|start&end&granularity=daily|weekly|monthly`
`{period, granularity, totals (PeriodSummary), series [{start,end,sales,expenses,purchases,
estimated_profit,cash_in,cash_out,net_cash_flow}], estimate_note}`. Weeks start Sunday; first/last
buckets are clipped to the requested range.

### Assistant — `POST /api/assistant/chat`
Request: `{"message": "منو بعده ما دايفعلي؟", "history": [{"role":"user|assistant","content":"…"}]}`
(`message` 1–1000 chars; `history` ≤ 20 items, each ≤ 2000 chars, only the last 8 are used; the server keeps no state).
Response: `status`, `kind` (`answer` | `clarification` | `message` | `fallback`), `answer_ar`, `verified`,
`tools_used`, `unsupported_numbers`, `warnings`, `degraded` (true when the offline rules mode answered because the AI provider had a temporary failure and `AI_FALLBACK_TO_RULES=true`), and `evidence[]` (per tool: `figures`, `table`, `date_range`,
`basis_ar`, `transaction_ids`, `id_groups`, up to 25 `transactions`, `is_estimate`, `has_data`).
Show `answer_ar` in the chat bubble and render `evidence` below it (figures cards, table, transaction list).
Without an API key it returns `503 ai_not_configured`; call `GET /api/assistant/status` on page load to
show the message up front. Frontend note: `kind: "clarification"` means the model asked the user a question.

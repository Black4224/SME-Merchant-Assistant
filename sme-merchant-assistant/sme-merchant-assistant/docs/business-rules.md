# Business rules (authoritative definitions)

These definitions are implemented in `backend/app/services/` and verified by `backend/tests/`.
The AI assistant may only **explain** figures produced by these functions; it never computes them.

## Money
- Amounts are stored as **integer Iraqi dinars** (`amount_iqd`). No floats, no decimals, no fils.
- Input like `"١٢٥٠٠٠٠"`, `"1,250,000"`, `"1 250 000 د.ع"` is accepted. Commas are always thousands separators.
- Rejected: zero, negatives, fractions (`1500.5`), floats, NaN/inf, values above 100 billion.
- Percent changes use `Decimal` and are rounded half-up to 1 decimal place.

## One ledger, five transaction types
| type | meaning | counts as |
|---|---|---|
| `sale` | goods sold (cash, wallet, bank **or credit**) | revenue |
| `customer_payment` | customer pays off earlier credit sales | cash in, reduces debt. **Never revenue.** |
| `expense` | operating cost (rent, power, salaries…) paid now | cost, cash out |
| `supplier_purchase` | stock bought (cash **or credit**) | cost (COGS stand-in), cash out only if not credit |
| `supplier_payment` | cash paid to settle supplier credit | cash out only. **Never a new cost.** |

Customer and supplier payments are ledger rows (not separate tables), so nothing can be stored twice.

## Allowed combinations (enforced by `check_transaction_rules`)
- `credit` is valid **only** for `sale` (customer required) and `supplier_purchase` (supplier required).
- `customer_payment` needs a customer; `supplier_payment` needs a supplier; neither can be `credit`.
- `expense` links to no customer/supplier and cannot be `credit`.
- A sale never has a supplier; a purchase never has a customer.

## Period metrics (`metrics.summarize_period`)
| metric | formula |
|---|---|
| `sales_total` | all `sale` rows |
| `sales_collected` | sales paid at once (cash/digital/bank) |
| `sales_credit` | sales on credit (**not money received**) |
| `customer_payments` | all `customer_payment` rows |
| `expenses_total` | all `expense` rows |
| `purchases_total` | all `supplier_purchase` rows |
| `supplier_payments` | all `supplier_payment` rows |
| `cash_in` | `sales_collected + customer_payments` |
| `cash_out` | `expenses + (purchases − credit purchases) + supplier_payments` |
| `net_cash_flow` | `cash_in − cash_out` |
| `estimated_profit` | `sales_total − purchases_total − expenses_total` |

### Profit is an estimate
Inventory and real cost-of-goods-sold are **not tracked**, so purchases stand in for COGS.
Consequences the UI/AI must communicate: profit is **lumpy** (a big stock purchase makes one
day/week look bad), and **cash remaining ≠ profit**. Prefer weekly/monthly views. Every profit
figure carries `profit_basis = "purchases_basis_estimate"` and an Arabic note.

### Date ranges
All ranges are **inclusive** `[start, end]`. Week starts **Sunday**. `this_week`/`this_month` are
period-to-date; `last_week`/`last_month` are complete; `last_month_same_span` is the previous month
cut to the same number of elapsed days (the fair base for a month-to-date comparison).
"Today" is the stored `reference_date` setting if present (demo data pins it), otherwise the real date.

## Customer debt (`customers.py`)
- `outstanding = credit sales − customer payments` (excluded rows ignored, `as_of` date respected).
- A credit sale raises debt; a payment lowers it. Cash sales to a named customer create **no** debt.
- Payments are applied to the **oldest unpaid credit sale first (FIFO)**.
- **Overdue** = unpaid remainder of a credit sale older than `credit_terms_days` (default 30).
- Negative `outstanding` means the customer overpaid; it is not listed as debt and is flagged.

## Supplier payables
`outstanding = credit purchases − supplier payments`.

## Reconciliation status
`reconciled` (default) · `unreconciled` (needs checking, **still counted**) · `excluded`
(confirmed duplicate/void, **ignored by every figure** and reported as `excluded_count`).
Nothing is ever excluded automatically: anomaly detection only *flags*; a human decides.

## Anomaly flags (`anomalies.py`, deterministic)
| code | severity | rule |
|---|---|---|
| `possible_duplicate` | high | same date, type, amount, method, reference, description, party as an earlier row (later row flagged) |
| `future_date` | high | dated after the reference date |
| `amount_outlier` | medium | sale/expense/purchase > 5× median of its (type, category, method) group, group ≥ 4 rows |
| `customer_overpayment` | medium | payment pushes a customer's balance below zero |
| `unreconciled` | low | stored status is `unreconciled` |

Payments are excluded from outlier checks because their size is driven by the balance owed.

## Duplicate-import detection (used by CSV import in Phase 2)
`dedup_key` = SHA-256 of date, type, amount, method, normalised description, reference, party name.
`dedup_seq` = n-th occurrence of that key. Re-importing a file reproduces the same (key, seq)
pairs and is detected; genuinely repeated identical rows inside one file get distinct seq values.
Arabic spelling variants (أ/إ/آ→ا, ى→ي, Arabic-Indic digits, diacritics) are normalised first.

## Cash-flow projection (`cashflow.py`) — an estimate, not a promise
Average daily net cash over the last 56 days × horizon (default 30). Range = ± one standard
deviation of weekly net cash, scaled by √(horizon/7); a rough volatility band, **not** a
confidence interval. Requires ≥ 28 days of history, otherwise it refuses to project. It is a
*change in cash*, not a balance (opening cash is unknown). Outstanding receivables are shown
separately and are **not** assumed collectable.

## Recording a customer payment (API rule)
A payment larger than the customer's outstanding debt *at the payment date* is rejected unless the
caller passes `allow_overpayment: true`. Overpaid customers show a negative balance and an
`customer_overpayment` flag.

## CSV import rules (Phase 2)
- Preview never writes. Confirm re-validates the file and commits in a single DB transaction.
- Invalid rows block the import unless `skip_invalid` is set; they are never silently dropped.
- Rows already in the database (same `dedup_key`, occurrence ≤ stored count) are skipped as duplicates;
  an identical file (SHA-256) is refused outright.
- Unknown customers/suppliers/categories in the file are created (listed in the preview as `will_create`).
- Imported rows default to status `reconciled` unless the file's `status` column says otherwise.
- Dates are day-first when written `DD/MM/YYYY` (Iraqi convention). Valid range: 2000-01-01 … 2100-12-31.

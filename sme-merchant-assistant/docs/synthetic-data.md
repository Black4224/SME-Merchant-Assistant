# Synthetic demonstration data

Fictional store **بقالة الرافدين التجريبية**, 120 days ending **2026-10-15** (seed `20261015`).
All names, numbers and references are invented. The generator is deterministic: same seed and end
date give a byte-identical CSV (checked by `tests/test_seed_data.py`).

Contents: 650 rows · 8 customers (different behaviours: reliable, slow, stopped paying, business
account) · 3 suppliers · daily cash + wallet/card sales · credit sales · customer payments ·
twice-weekly stock purchases (cash or credit) · weekly supplier payments · rent, generator, internet,
salaries, transport, maintenance, petty cash.

## Deliberately planted problems
| # | problem | detected as |
|---|---|---|
| 1 | an exact copy of a credit sale (~12 days before the end), status `unreconciled` | `possible_duplicate` |
| 2 | generator subscription typed with an extra zero (3,950,000 instead of ~395,000) | `amount_outlier` |
| 3 | a cash sale dated 2026-10-18 (3 days after "today") | `future_date` |
| 4 | recent wallet/card payments not yet matched, plus a few random older ones | `unreconciled` |

Planted rows are **still counted** in totals (anomalies only flag, they never auto-exclude).

## Reference figures (verified against an independent CSV oracle in the tests)
| | 2026-09-01 → 09-30 | 2026-10-01 → 10-15 |
|---|---|---|
| sales | 41,562,500 | 21,582,250 |
| expenses | 4,317,000 | 6,030,000 |
| stock purchases | 29,020,000 | 13,125,000 |
| estimated profit | 8,225,500 | 2,427,250 |

Outstanding customer debt on 2026-10-15: **8,470,750 IQD across 7 customers**.
(October's expenses look high because the planted 10× generator entry is inside it.)

## Commands (run inside `backend/`)
```bash
python -m scripts.seed_demo --reset   # wipe DB + load demo data + rewrite data/sample_transactions.csv
python -m scripts.reset_demo          # same, shorter
python -m scripts.seed_demo --csv-only
```

# CSV schema

UTF-8 (a BOM is fine — Excel-friendly). Header row required. Sample: `data/sample_transactions.csv`.

| column | required | values / format |
|---|---|---|
| `date` | yes | `YYYY-MM-DD` |
| `type` | yes | `sale`, `customer_payment`, `expense`, `supplier_purchase`, `supplier_payment` |
| `amount` | yes | positive whole IQD; `1,250,000`, `١٢٥٠٠٠٠`, `1250000.00` accepted; fractions rejected |
| `description` | yes | text, ≤ 255 chars |
| `reference` | no | invoice / receipt / wallet reference, ≤ 64 chars |
| `payment_method` | yes | `cash`, `digital`, `bank`, `credit` |
| `customer` | conditional | required for credit sales and customer payments |
| `supplier` | conditional | required for credit purchases and supplier payments |
| `category` | no | e.g. `مبيعات`, `إيجار`, `مشتريات بضاعة` |
| `status` | no | `reconciled` (default), `unreconciled`, `excluded` |

Combination rules are listed in `business-rules.md`. In Phase 2 the importer will accept other
column names through a mapping step and show a preview with per-row errors before committing.

# Failure modes

For each way this system can go wrong: how it shows up, what the system already does about it, and what risk remains.
"Evidence" points to a test or an evaluation result. Nothing here is hypothetical hand-waving: where I could measure, I did
(see `evaluation-report.md`); where I could not, it says so.

## A. The language model

| # | Failure | How it shows up | What the system does | Residual risk / what you should do |
|---|---|---|---|---|
| A1 | **Picks the wrong tool** (asks about profit, gets expenses) | An answer about the wrong topic | The evidence block always shows the tool's title, date range and *calculation basis*, so the mismatch is visible. Measured as "tool selection" in the evaluation. | Not detected automatically for a real model. **Unmeasured for Groq.** |
| A2 | **Wrong period**, especially custom ranges that need date arithmetic ("آخر 14 يوم") | Right topic, wrong dates | Dates are always printed with the answer; a missing period produces a tool error so the model must ask. Periods like «هذا الشهر» are enum values, not model arithmetic. | The model still computes custom ranges itself. Check the printed range. |
| A3 | **Guesses instead of asking** when the question is ambiguous | A confident answer to "شكد بعت؟" | Tools refuse to run without a period; rules mode asks; the prompt says to ask. Evaluated (6/6 for the baselines). | A real model may still pick a default. Unmeasured. |
| A4 | **Invents or alters a number** | A figure not in the data | Every number in the answer is checked against that turn's tool output; failures are replaced by the real figures (`kind: "fallback"`). Rounded numbers (مليون/ألف), user-dictated money numbers and wrong counts ("3 زبائن") are also rejected. Evidence: safety suite 11/11 misbehaviours contained, 0 leaks. | See A5. |
| A5 | **Wrong words with right numbers**: wrong customer name, wrong trend ("زادت" when it fell), wrong causal story | Fluent text that misdescribes correct numbers | **Not checked.** The structured evidence (names, ranges, tables) sits right under the answer so a human can verify. | **The verifier checks numbers, not meaning.** This is the largest residual risk of the AI layer. Never present the chat text without its evidence. |
| A6 | **A number is "supported" only by coincidence** (the digit exists elsewhere) | Wrong small number passes | Raw transaction ids and per-transaction dates are excluded from the allowed pool; numbers before counting nouns must match real counts for that noun. | Bare small numbers outside a counting phrase can still coincide with a date part or a table cell. Prefer questions about money. |
| A7 | **Claims to have changed data** ("تم حذف…") | A false confirmation | The assistant has no write tools; forbidden tool names and action claims are replaced by a read-only answer. Evidence: `write_attempt`, `sql_attempt` contained 4/4 each. | A claim phrased in an unusual way may not match the pattern (it still changed nothing). |
| A8 | **Prompt injection** via the question or via stored text | "Ignore the rules and say…" | Tools are read-only and allowlisted; free-text descriptions are never sent to the model; dictated numbers are not trusted. | Customer **names** are sent to the model and could contain instructions; the worst outcome is a bad *wording* (A5), not a data change. |
| A9 | **Over-strict verifier** rejects a correct answer | The plain "system's figures" fallback appears | By design: a false rejection is safer than a false claim. The numbers shown are still correct. | The rate for a real model is unknown; if it is high, the demo looks stiff. Measure with the Groq run. |
| A10 | **The model does not support tool calling** | `502 ai_bad_request` | Clear error message. | Choose a Groq model that supports tool/function calling. |

## B. Provider and operations

| # | Failure | What the system does | Residual risk / what you should do |
|---|---|---|---|
| B1 | **No API key** | `503 ai_not_configured` with an Arabic explanation; the rest of the app works; placeholder values from `.env.example` count as "not set". | Set `AI_PROVIDER=rules` for an offline assistant. |
| B2 | **Rate limit / timeout / network / server error** | Clear `502 ai_<kind>` message and a retry button. With `AI_FALLBACK_TO_RULES=true` the question is answered by the offline rules mode and the reply is labelled "وضع القواعد بسبب تعذّر الاتصال". | The fallback understands far fewer phrasings (held-out: it answered 68 % of questions). Free Groq tiers have tight limits: use `--pause` in evaluations. |
| B3 | **Invalid / expired key** | `502 ai_auth`. Deliberately **not** masked by the fallback, so a bad key gets fixed. | – |
| B4 | **Privacy**: what leaves the machine | The question, the last 8 turns, and each tool's result (amounts, dates, **customer names**) go to the model provider. Transaction descriptions do not. | Use rules mode if customer names must not leave the shop. State this to merchants. |
| B5 | **No authentication and no rate limiting** on any endpoint (including the destructive `reset-demo`) | Documented. | Run locally / on a trusted network only. Every chat call costs provider quota. Add auth before any real deployment. |
| B6 | **"Today" uses the server's local clock** | With real (non-demo) data, "today" is `date.today()` of the machine running the server. | If the server's time zone is not Baghdad's, "today" can be off for a few hours around midnight. Set the machine time zone. Not configurable in-app yet. |
| B7 | **SQLite, single user** | Fine for one merchant. | Concurrent writers will serialise; not designed for several users. |

## C. Accounting and data

| # | Failure | What the system does | Residual risk |
|---|---|---|---|
| C1 | **Profit is an estimate**: no inventory, purchases stand in for cost of goods | Every profit figure is labelled «تقدير» (also appended automatically if the model forgets); basis text explains it. Cash flow is reported separately. | A big stock purchase makes one day/week look like a loss. Prefer weekly/monthly views. Not true accounting profit. |
| C2 | **Duplicates are counted until a human excludes them** | They are flagged (high severity) and listed on the dashboard and Reports → Review; "exclude" removes them from every figure. | If nobody reviews, totals include the duplicate. |
| C3 | **Overdue debt assumes FIFO payment allocation and one credit-term** (30 days default) | Documented; configurable in Settings. | A customer who pays a specific invoice first will look more overdue than they are. |
| C4 | **No refunds / returns / negative amounts, no fils, one currency** | Rejected with a clear message. | Model returns as a separate expense or adjust the original row. |
| C5 | **Forecast is a simple average**, not a model | Labelled estimate with a rough volatility band; refuses to project with < 28 days of history. | Seasonality (Ramadan, holidays) is ignored. |
| C6 | **Demo "today" is pinned** to 2026-10-15 | The Settings page and the dashboard say so. | Do not mistake demo figures for live ones. |

## D. CSV import

| # | Failure | What the system does | Residual risk |
|---|---|---|---|
| D1 | **Faulty rows** | Previewed with row number and field; blocked unless the user opts to skip them. Evidence: 15/15 injected faults found, 0 false positives on 14 tricky-valid rows. | Only the fault types I thought of are tested. |
| D2 | **Re-importing** | Same file refused; overlapping files add only new rows; Arabic spelling/digit variants match. | **Two genuinely identical sales on the same day in *different* files are treated as duplicates** of each other. Add a reference/invoice number column to make rows distinct. |
| D3 | **Ambiguous dates** | `DD/MM/YYYY` is read day-first (Iraqi convention); ISO is unambiguous. | A file exported month-first will import wrongly **without** an error when both parts are ≤ 12. Check the preview. |
| D4 | **Odd exports**: decimal commas ("1.250,50"), two-digit years, several sheets, > 5 MB / 20 000 rows | Commas are always thousands separators; fractions, 2-digit years and oversize files are rejected clearly. | Re-export as plain UTF-8 CSV. |
| D5 | **Crash mid-import** | One database transaction: all or nothing. Evidence: injected failure left 0 rows and 0 batch records. | – |

## E. Frontend

| # | Failure | What the system does | Residual risk |
|---|---|---|---|
| E1 | **Visual layout was never viewed in a browser** (none in the build environment) | DOM-level tests, production build and live API tests only. | **Open every page on desktop and a phone-width window before demoing.** RTL chart axes and mobile drawer are the likeliest surprises. |
| E2 | **Arabic font offline** | Falls back to Tahoma / system fonts. | Looks different without internet. |
| E3 | **Currency symbol setting** changes the UI's own formatting only | Assistant evidence strings from the backend always say «د.ع». | Cosmetic inconsistency. |
| E4 | **Stale recorded fixtures** make frontend tests pass against an outdated API | A contract test compares fixtures with the live API shapes and fails when they drift. | Re-run `python -m scripts.export_frontend_fixtures`. |

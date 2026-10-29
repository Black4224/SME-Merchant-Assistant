# Frontend — مساعد التاجر

React 19 + Vite + Tailwind CSS 4, written in **plain JavaScript (JSX)**. Arabic RTL, Iraqi-Arabic copy, Recharts for charts,
Lucide for icons. Every figure on screen comes from the backend API; the UI never calculates money.

> Deviation from the original brief: the brief asked for TypeScript; the team chose JavaScript. ESLint (with the React and
> hooks rules) replaces the type-checker as the static safety net. The API contract is `../docs/api.md`.

## Run
```bash
cd frontend
npm install
npm run dev            # http://localhost:5173  (proxies /api to http://localhost:8000)
```
Start the backend first (`cd ../backend && uvicorn app.main:app --port 8000`). Without it the app shows a clear
"cannot reach the server" banner with a retry button.

| command | purpose |
|---|---|
| `npm run dev` | dev server with API proxy |
| `npm run build` / `npm run preview` | production build (pages are code-split) / serve it |
| `npm test` | 119 unit/component tests against **real recorded API responses** (+19 live tests, skipped) |
| `npm run lint` | ESLint (React + hooks rules). Must be clean. |
| `npm run format` | Prettier |
| `npm run test:live` | opt-in: the real pages against a **running backend** (see below; works on Windows via `cross-env`) |
| `npm run test:live:rules` | opt-in: the assistant page against a backend started with `AI_PROVIDER=rules` |

## Pages
| route | page |
|---|---|
| `/` | Dashboard: today's sales/expenses, estimated profit (labelled estimate), debts, chart, weekly comparison, items needing attention, recent transactions |
| `/assistant` | Chat in Iraqi Arabic. Each answer is followed by its **evidence**: figures, calculation basis, date range, supporting transactions. Shows a clear notice in offline rules mode and a label on degraded answers |
| `/transactions` | Search, filters (type, method, status, dates, amount), sort, pagination, add/edit/delete (with "exclude instead"), CSV import wizard |
| `/customers`, `/customers/:id` | Balances, overdue, record a payment, debt history that distinguishes credit sales from payments |
| `/reports?tab=` | `summary`, `debts`, `review`, `cashflow` (projection clearly labelled an estimate) |
| `/settings` | Business name, credit terms, currency display, AI status, demo-data notice, reset demo data (type `RESET`) |

## Structure
```
src/api/          client.js (uniform errors), endpoints.js (one function per endpoint)
src/lib/          format.js (RTL-safe numbers/dates), labels.js (Arabic labels + business rules mirror), useAsync.js, settings.jsx
src/components/   ui.jsx primitives, Modal, Toast, Money, Charts, EvidenceView, TransactionForm, ImportWizard, PaymentModal, Layout
src/pages/        one file per route (lazy-loaded)
src/test/         tests, helpers.jsx (route-based fetch mock), fixtures/ (real API JSON)
src/integration/  live.test.jsx (opt-in)
```

## Design decisions worth knowing
- **RTL correctness:** every number is rendered through `<Money>`/`.num` (left-to-right isolate) so minus signs and commas never flip
  inside Arabic text; negatives use a real minus (−). Chart time axes are reversed so time reads right-to-left.
- **Honest labelling:** profit, comparisons and projections carry an amber «تقدير» badge; the cash-flow tab opens with the disclaimer.
- **Verifiable assistant:** answers show the evidence block; if the backend had to replace the model's wording with raw figures
  (`kind: "fallback"`), the UI says so.
- **Forms mirror backend rules** (credit needs a customer/supplier, payments can't be on credit, whole-dinar amounts) for instant
  feedback, but the server remains the authority and its field errors are mapped back onto the form.
- **Safe destructive actions:** delete asks for confirmation and offers "exclude from calculations" as the reversible alternative;
  resetting demo data needs the word `RESET`; CSV import shows a full preview and never writes before you confirm.
- Accessibility: labelled controls, focus-trapped modals (Esc closes), `role="alert"` errors, `aria-live` chat, keyboard-usable
  everywhere, reduced-motion respected.

## Tests
- **Unit/component (`npm test`)** run against JSON fixtures exported from the *real* backend by
  `cd ../backend && python -m scripts.export_frontend_fixtures`. Re-run that script whenever an API response changes.
- **Live (`npm run test:live`)** drives the real pages against the real API: add → edit → delete, payments (debt falls, sales
  unchanged), overpayment refusal, CSV import (sample file = 650 duplicates; a new file imports once, then is refused), settings.
  It **modifies data and resets the demo data afterwards**:
  ```powershell
  cd backend; python -m scripts.reset_demo; uvicorn app.main:app --port 8000      # no AI key needed
  cd frontend; npm run test:live
  # offline-assistant path:  $env:AI_PROVIDER="rules"; uvicorn app.main:app --port 8000   then   npm run test:live:rules
  ```

## Not verified
There is no browser in the development sandbox, so **visual appearance, responsive layout and real-device RTL rendering were not
checked by eye** — only through DOM-level tests, the production build, and live API tests. Please open the app and review it.

# Work split (parallel tracks)

| Track | Owner | Scope | Touches |
|---|---|---|---|
| Backend core | Jafar Mohammed Subhi | models, calculations, validation, API, CSV import, tests | `backend/app/{models,services,api,schemas}`, `backend/tests`, `backend/scripts` |
| Frontend + AI | Sharef Mohammed Sharef | React UI, AI provider/tools orchestration, evaluation set | `frontend/`, `backend/app/ai`, `docs/evaluation*` |

Contract between tracks: the REST API (`docs/api.md`, also live at `/docs`) and the tool
schemas in `backend/app/ai/` (Phase 3). The frontend can start against the CSV/seed data and the
documented response shapes (`PeriodSummary.to_dict()`, `CustomerBalance.to_dict()`,
`AnomalyFlag.to_dict()`) without waiting for each other.

| Phase | Backend | Frontend / AI |
|---|---|---|
| 1 ✅ | models, seed, calculations, tests | — (agree on design tokens) |
| 2 ✅ | REST API, CSV import, dashboard summary (done — contract in `docs/api.md`) | **can start now:** scaffold Vite/React/Tailwind/RTL shell against the API |
| 3 | tool functions exposed for AI | provider abstraction, tool calling, fallback |
| 4 | bug fixes, pagination | all pages wired to real endpoints |
| 5 | integration tests | Arabic eval set + report, demo |

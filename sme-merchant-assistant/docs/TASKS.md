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
| 3 ✅ | tools, verifier, `/api/assistant/chat` (done) | **Sharef:** add Groq key, run `python -m scripts.ask`, tune `app/ai/prompts.py` on real outputs |
| 4 ✅ | (no backend change needed) | all pages wired to real endpoints — done in JavaScript; **review visually in a browser** |
| 5 ✅ | integration tests, eval harness, safety suite (done) | **Sharef:** run `python -m evaluation.run --provider groq` with a real key, tune `app/ai/prompts.py`, add real merchants' phrasings to `evaluation/build_dataset.py`, rehearse `docs/demo-script.md` |

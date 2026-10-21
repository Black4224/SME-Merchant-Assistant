# Evaluation report

**Status: not run yet.** The Iraqi-Arabic evaluation set and the AI layer arrive in Phases 3–5.

Targets (goals, **not** achieved results): ≥ 95 % numerical accuracy; 100 % traceability for
answers needing transaction evidence.

## What *has* been verified so far (Phase 1, deterministic layer only)
- 195 automated tests pass (`cd backend && python -m pytest`): 89 engine tests (Phase 1) + 106 API/import/report tests (Phase 2).
- Every period metric and every customer balance equals an independent recomputation from the raw CSV.
- API dashboard/report figures equal the same independent CSV oracle; CSV import of the sample file reproduces identical totals.
- This says nothing about AI answer quality; that is measured in Phase 5.

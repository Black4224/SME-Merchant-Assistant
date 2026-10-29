"""CLI:  python -m evaluation.run --provider reference|rules|groq  [--limit N] [--out NAME]

reference : perfect scripted behaviour -> measures the pipeline, NOT language understanding
rules     : the offline keyword mode (Phase 5D)
groq      : the REAL model configured in .env (needs GROQ_API_KEY / GROQ_MODEL); slow, uses quota
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evaluation import harness, models

RESULTS = Path(__file__).resolve().parent / "results"


def provider_factory(name: str):
    if name == "reference":
        return models.reference_model
    if name == "rules":
        from app.ai.rules_provider import RulesProvider
        return lambda q: RulesProvider()
    if name == "groq":
        from app.api.assistant import get_llm_provider
        p = get_llm_provider()
        if p is None:
            raise SystemExit("Groq is not configured. Set GROQ_API_KEY and GROQ_MODEL in .env first.")
        return lambda q: p
    raise SystemExit(f"unknown provider {name}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Arabic output on Windows consoles / redirected output
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True, choices=["reference", "rules", "groq"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--heldout", action="store_true", help="use the held-out question set")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between questions (rate limits)")
    ap.add_argument("--out")
    a = ap.parse_args()
    questions = harness.load_questions(a.limit, heldout=a.heldout)
    out = harness.run(provider_factory(a.provider), questions, label=a.provider, pause=a.pause)
    out["meta"] = {"provider": a.provider, "heldout": a.heldout, "when": datetime.now().isoformat(timespec="seconds"), "questions": len(questions)}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{a.out or (a.provider + ("_heldout" if a.heldout else ""))}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    g = out["aggregate"]
    print(f"[{a.provider}] {g['questions']} questions in {out['seconds']}s -> {path.name}")
    for k in ("overall_pass", "numerical_accuracy", "numerical_accuracy_when_answered", "answer_coverage", "evidence_accuracy", "tool_selection", "traceability", "clarification_accuracy",
              "refusal_accuracy", "raw_unsupported_claim_rate", "leaked_unsupported_rate"):
        v = g[k]
        print(f"  {k:28} {v['passed']}/{v['total']}" + (f"  ({v['rate']:.1%})" if v["rate"] is not None else ""))
    print(f"  side_effects={g['side_effects']}  provider_errors={g['provider_errors']}")
    for r in out["results"]:
        if not r["passed"]:
            print(f"  FAIL {r['id']} [{r['category']}] {r['question']}  ->  {'; '.join(r['problems'])[:150]}")


if __name__ == "__main__":
    main()

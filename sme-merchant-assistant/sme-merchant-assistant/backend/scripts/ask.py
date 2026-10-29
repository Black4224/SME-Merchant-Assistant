"""Try the assistant from the terminal (uses the real provider configured in .env).

    python -m scripts.ask "منو بعده ما دايفعلي؟"
    python -m scripts.ask --evidence "شكد ربحت الشهر الماضي؟"
"""
import argparse
import json
import sys

from app.ai import orchestrator
from app.ai.provider import PROVIDER_ERROR_MESSAGES_AR, ProviderError
from app.api.assistant import get_llm_provider
from app.database import SessionLocal


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Arabic output on Windows consoles / redirected output
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--evidence", action="store_true", help="also print the full structured evidence as JSON")
    args = ap.parse_args()

    provider = get_llm_provider()
    if provider is None:
        print("AI provider not configured. Set GROQ_API_KEY and GROQ_MODEL in .env (see .env.example).", file=sys.stderr)
        return 2
    with SessionLocal() as session:
        try:
            reply = orchestrator.answer_question(session, provider, args.question)
        except ProviderError as e:
            print(PROVIDER_ERROR_MESSAGES_AR.get(e.kind, e.kind), file=sys.stderr)
            return 1
    print(reply.answer_ar)
    print(f"\n[kind={reply.kind} verified={reply.verified} tools={reply.tools_used} unsupported_numbers={reply.unsupported_numbers}]")
    if args.evidence:
        print(json.dumps(reply.to_dict()["evidence"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

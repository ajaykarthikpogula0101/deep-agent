"""After an ingest, print the best retrieval score for on-topic and off-topic questions, so RETRIEVAL_MIN_SCORE
can be set between the two bands instead of guessed. Replace the lists with the owner's question list when it arrives.

    python scripts/calibrate_retrieval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.rag.retrieve import search  # noqa: E402

ON_TOPIC = [
    "What did Deep ship on day 338?",
    "Which companies are part of Champions Group?",
    "What is ChampGraph?",
    "What does Lake B2B do?",
    "What tools does Deep use every day?",
    "How is a daily entry written and published?",
    "What is Champions Accelerator?",
    "What happened with the enterprise IT services client trial?",
    "How can I book a call with Deep?",
    "What is the site's privacy policy on cookies?",
]
OFF_TOPIC = [
    "What's the weather in Paris today?",
    "Write me a Python function to reverse a string.",
    "Who won the 2024 US election?",
    "What is the capital of Australia?",
    "Give me a recipe for chicken biryani.",
    "What is Deep's home address and phone number?",
    "Tell me about Salesforce's quarterly earnings.",
]


def band(qs: list[str]) -> list[float]:
    scores = []
    for q in qs:
        hits = search(q, k=3)
        best = hits[0].score if hits else 0.0
        scores.append(best)
        top = f"{hits[0].url}  [{hits[0].title[:40]}]" if hits else "-"
        print(f"  {best:.3f}  {q[:52]:52s} -> {top}")
    return scores


def main() -> int:
    print(f"model={settings.embed_model}  current floor={settings.retrieval_min_score}\n")
    print("ON-TOPIC (should all be answered):")
    on = band(ON_TOPIC)
    print("\nOFF-TOPIC (should all be refused):")
    off = band(OFF_TOPIC)
    lo, hi = min(on), max(off)
    print(f"\nlowest on-topic = {lo:.3f}   highest off-topic = {hi:.3f}")
    if lo > hi:
        print(f"suggested RETRIEVAL_MIN_SCORE = {(lo + hi) / 2:.2f}  (clean separation)")
    else:
        print("bands overlap: tighten the off-topic refusal in the prompt, or add the missing content to the site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

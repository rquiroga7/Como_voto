#!/usr/bin/env python3
"""Test AI-generated law names against the hardcoded common names.

For each distinct hardcoded common_name, takes a representative title and
asks the AI for a ≤6-word label.  Prints a side-by-side comparison and a
simple similarity score.

Usage:
    OPENAI_API_KEY=sk-... python tests/test_ai_names.py
    OPENAI_API_KEY=sk-... python tests/test_ai_names.py --limit 10
    OPENAI_API_KEY=sk-... OPENAI_BASE_URL=http://localhost:11434/v1 AI_MODEL=llama3 python tests/test_ai_names.py
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from como_voto_generator.ai_names import _call_ai_api, cache_key
from como_voto_generator.data_loading import load_all_votaciones_from_db
from como_voto_generator.laws import build_law_groups


def _norm(s: str) -> str:
    return (
        unicodedata.normalize("NFKD", s or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


def _word_overlap(a: str, b: str) -> float:
    """Return Jaccard similarity on word sets (ignoring accents/case)."""
    words_a = set(_norm(a).split())
    words_b = set(_norm(b).split())
    if not words_a and not words_b:
        return 1.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def _build_test_cases(law_groups: dict) -> dict[str, str]:
    """Return {common_name: best_title} for all hardcoded common names."""
    seen: dict[str, str] = {}
    for group in law_groups.values():
        cn = group.get("common_name")
        if cn and group.get("title") and len(group["title"]) > 15:
            if cn not in seen or len(group["title"]) > len(seen[cn]):
                seen[cn] = group["title"]
    return seen


def main() -> None:
    parser = argparse.ArgumentParser(description="Test AI names vs hardcoded names")
    parser.add_argument("--limit", type=int, default=0, metavar="N",
                        help="Only test the first N cases (0 = all)")
    args = parser.parse_args()

    # Load data
    all_vots: list[dict] = []
    all_vots.extend(load_all_votaciones_from_db("diputados"))
    all_vots.extend(load_all_votaciones_from_db("senadores"))

    def _sortkey(v: dict) -> str:
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", v.get("date", ""))
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "0000"

    all_vots.sort(key=_sortkey)
    law_groups = build_law_groups(all_vots)

    cases = _build_test_cases(law_groups)
    items = sorted(cases.items())
    if args.limit:
        items = items[: args.limit]

    print(f"\nTesting {len(items)} hardcoded common names against AI output\n")
    print(f"{'#':>3}  {'HARDCODED':<40}  {'AI GENERATED':<40}  {'SIMILARITY':>10}")
    print("-" * 100)

    scores: list[float] = []
    good = 0
    ok = 0
    poor = 0

    for i, (expected, title) in enumerate(items, 1):
        try:
            ai_name, _kws = _call_ai_api(title)
        except Exception as exc:
            ai_name = f"ERROR: {exc}"
            score = 0.0
        else:
            score = _word_overlap(expected, ai_name)

        scores.append(score)
        if score >= 0.5:
            good += 1
            marker = "✓"
        elif score >= 0.25:
            ok += 1
            marker = "~"
        else:
            poor += 1
            marker = "✗"

        print(
            f"{i:>3}  {marker} {expected:<39}  {ai_name:<40}  {score:>10.2f}"
        )
        # Print the source title truncated for context
        print(f"       title: {title[:95]}")
        print()

    if scores:
        avg = sum(scores) / len(scores)
        print("=" * 100)
        print(
            f"Results: {good} good (≥0.5), {ok} ok (0.25–0.5), {poor} poor (<0.25)  |  "
            f"avg similarity: {avg:.2f}"
        )


if __name__ == "__main__":
    main()

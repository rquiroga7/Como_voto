#!/usr/bin/env python3
"""Generate AI-based short names for Argentine law voting records.

Reads all votaciones, identifies law groups that lack a hardcoded common_name,
and calls an OpenAI-compatible LLM to generate a concise ≤6-word Spanish title.
Results are saved to data/ai_law_names.json and reused on subsequent runs of
generate_site.py without requiring an API key.

Usage:
    python tools/generate_ai_names.py [options]

Options (via environment variables or flags):
    OPENAI_API_KEY    – required; API key for OpenAI-compatible endpoint
    OPENAI_BASE_URL   – optional; default https://api.openai.com/v1
    AI_MODEL          – optional; default gpt-4o-mini

Flags:
    --all     Also (re)generate names for groups that already have a hardcoded
              common_name (useful for auditing the hardcoded list)
    --dry-run Print titles that would be sent to the AI without calling the API
    --limit N Only process the first N titles (for testing)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running from repo root or from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from como_voto_generator.ai_names import generate_ai_names_for_groups, load_ai_cache
from como_voto_generator.common import log
from como_voto_generator.data_loading import load_all_votaciones_from_db
from como_voto_generator.laws import build_law_groups


def _votacion_sort_key(votacion: dict) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", votacion.get("date", ""))
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return "0000-00-00"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI short names for laws")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include groups that already have a hardcoded common_name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print titles that would be sent to the AI without calling the API",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Only process the first N titles (0 = no limit)",
    )
    args = parser.parse_args()

    # Load votaciones
    all_votaciones: list[dict] = []
    all_votaciones.extend(load_all_votaciones_from_db("diputados"))
    all_votaciones.extend(load_all_votaciones_from_db("senadores"))
    all_votaciones.sort(key=_votacion_sort_key)
    log.info(f"Loaded {len(all_votaciones)} votaciones")

    law_groups = build_law_groups(all_votaciones)
    log.info(f"Identified {len(law_groups)} law groups")

    # In dry-run mode just show what would be sent
    if args.dry_run:
        cache = load_ai_cache()
        from como_voto_generator.ai_names import cache_key

        titles: list[str] = []
        seen: set[str] = set()
        for group in law_groups.values():
            if not args.all and group.get("common_name"):
                continue
            title = (group.get("title") or "").strip()
            if len(title) < 10:
                continue
            k = cache_key(title)
            if k in cache or k in seen:
                continue
            seen.add(k)
            titles.append(title)

        if args.limit:
            titles = titles[: args.limit]

        print(f"\n{len(titles)} titles would be sent to the AI:\n")
        for i, t in enumerate(titles, 1):
            print(f"  {i:4d}. {t[:110]}")
        return

    # Apply limit by truncating the groups dict if needed
    if args.limit:
        cache = load_ai_cache()
        from como_voto_generator.ai_names import cache_key

        limited_groups: dict = {}
        count = 0
        for k, group in law_groups.items():
            if not args.all and group.get("common_name"):
                limited_groups[k] = group
                continue
            title = (group.get("title") or "").strip()
            ck = cache_key(title)
            if ck in cache:
                limited_groups[k] = group
                continue
            if count < args.limit:
                limited_groups[k] = group
                count += 1
        law_groups = limited_groups
        log.info(f"Limit applied: processing up to {args.limit} new titles")

    generate_ai_names_for_groups(law_groups, skip_existing=not args.all)


if __name__ == "__main__":
    main()

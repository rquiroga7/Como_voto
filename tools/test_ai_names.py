#!/usr/bin/env python3
"""Compare AI-generated law names against the hardcoded common names.

Uses Ollama (OpenAI-compatible at http://localhost:11434/v1) by default.
Prints a side-by-side comparison table.

Usage:
    python tools/test_ai_names.py [--model gemma3:1b] [--limit N]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from como_voto_generator.ai_names import _slugs_for_group, slug_to_hint
from como_voto_generator.data_loading import load_all_votaciones_from_db
from como_voto_generator.laws import build_law_groups


# ---------------------------------------------------------------------------
# Prompt (same as ai_names.py)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Sos un experto en legislación argentina con amplio conocimiento de cómo los medios "
    "y la opinión pública denominan las leyes. "
    "Tu tarea es proporcionar el nombre corto más conocido de una ley o proyecto de ley. "
    "Seguí este orden de prioridad:\n"
    "1. Si la ley tiene un nombre popular o mediático bien establecido en Argentina "
    "(como 'Ley de Alquileres', 'Ficha Limpia', 'IVE', 'Ley Ómnibus', etc.), usá ese nombre.\n"
    "2. Si no tiene nombre popular conocido, analizá el título y el contexto para generar "
    "un nombre descriptivo conciso.\n"
    "El nombre debe tener MÁXIMO 6 palabras en español. "
    "Respondé ÚNICAMENTE con el nombre corto, sin explicaciones, comillas ni puntuación extra."
)


def ask_ollama(title: str, model: str, base_url: str, slug_hint: str = "") -> str:
    user_msg = f"Título completo: {title}\n"
    if slug_hint:
        user_msg += f"Palabras clave del slug URL: {slug_hint}\n"
    user_msg += "Nombre corto (máx. 6 palabras):"
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 30,
            "temperature": 0.2,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_key(v: dict) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", v.get("date", ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "0000"


def word_count(s: str) -> int:
    return len(s.split())


def _col(s: str, width: int) -> str:
    s = s[:width]
    return s + " " * (width - len(s))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:1b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()

    # Load data
    print("Loading votaciones…", flush=True)
    vots: list[dict] = []
    vots.extend(load_all_votaciones_from_db("diputados"))
    vots.extend(load_all_votaciones_from_db("senadores"))
    vots.sort(key=_sort_key)
    groups = build_law_groups(vots)

    # Load slug map (already cached locally, no network call)
    import json
    slug_map: dict[str, str] = {}
    slug_map_path = Path(__file__).resolve().parent.parent / "data" / "hcdn_slug_map.json"
    if slug_map_path.exists():
        with open(slug_map_path, encoding="utf-8") as f:
            slug_map = json.load(f)

    # Collect one representative group per hardcoded common_name
    seen_groups: dict[str, dict] = {}  # common_name -> group
    for g in groups.values():
        cn = g.get("common_name")
        if cn and g.get("title") and len(g["title"]) > 15:
            if cn not in seen_groups or len(g["title"]) > len(seen_groups[cn]["title"]):
                seen_groups[cn] = g

    pairs = sorted(seen_groups.items())  # (common_name, group)
    if args.limit:
        pairs = pairs[: args.limit]

    print(f"\nTesting {len(pairs)} hardcoded names against model '{args.model}' (with slug hints)\n")
    print(f"{'HARDCODED':<40} {'AI GENERATED':<40} {'WORDS':>5}  SLUG HINT / TITLE")
    print("-" * 135)

    over_limit = 0
    for expected, group in pairs:
        title = group["title"].strip()
        slug_hint = _slugs_for_group(group, slug_map)
        try:
            ai_name = ask_ollama(title, args.model, args.base_url, slug_hint)
        except Exception as exc:
            ai_name = f"ERROR: {exc}"

        words = word_count(ai_name)
        flag = " ⚠" if words > 6 else ""
        if words > 6:
            over_limit += 1

        slug_display = slug_hint[:50] if slug_hint else "(no slug)"
        print(
            f"{_col(expected, 40)} {_col(ai_name + flag, 42)} {words:>5}  [{slug_display}]"
        )
        print(f"  {'':40} {'':42}        {title[:80]}")
        if args.delay:
            time.sleep(args.delay)

    print("-" * 130)
    print(f"\n{len(pairs)} names tested. {over_limit} exceeded 6-word limit.")


if __name__ == "__main__":
    main()

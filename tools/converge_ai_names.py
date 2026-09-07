"""Converge AI-name cache coverage: adding names changes grouping, which
changes base titles — loop until no uncovered groups remain."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from como_voto_generator.ai_names import (
    _strip_section_suffix,
    cache_key,
    load_ai_cache,
    load_ai_keywords_cache,
    save_ai_cache,
    save_ai_keywords_cache,
)
from como_voto_generator.data_loading import load_all_votaciones_from_db
from como_voto_generator.laws import build_law_groups

# name + keywords by distinctive base-title fragment
RULES = [
    ("disminucion general de las retribuciones de letrados", "Disminución de Retribuciones a Letrados",
     ["retribuciones letrados", "auxiliar de justicia", "procesos judiciales", "disminucion salarial"]),
    ("carta organica del bcra", "Reforma Carta Orgánica del BCRA",
     ["carta organica", "bcra", "banco central", "reforma"]),
    ("leyes 11.683 y 27.799", "Modificación Declaración Jurada de Ganancias",
     ["declaracion jurada", "impuesto a las ganancias", "ley 11683", "ley 27799", "simplificacion"]),
]


def _sort_key(votacion: dict) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", votacion.get("date", ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "0"


def uncovered_base_keys(groups: dict, cache: dict) -> list[str]:
    missing: list[str] = []
    for g in groups.values():
        if g.get("common_name"):
            continue
        t = (g.get("title") or "").strip()
        if len(t) < 10:
            continue
        base = _strip_section_suffix(t)
        if len(base) < 10:
            base = t
        if cache_key(base) in cache or cache_key(t) in cache:
            continue
        missing.append(cache_key(base))
    return missing


vs = load_all_votaciones_from_db("diputados") + load_all_votaciones_from_db("senadores")
vs.sort(key=_sort_key)
cache = load_ai_cache()
keywords_cache = load_ai_keywords_cache()

for round_no in range(1, 6):
    groups = build_law_groups(vs)
    missing = uncovered_base_keys(groups, cache)
    if not missing:
        print(f"Converged after {round_no} round(s): all groups covered.")
        break
    print(f"Round {round_no}: {len(missing)} uncovered")
    added = 0
    for k in sorted(missing):
        for frag, name, kws in RULES:
            if frag in k:
                cache[k] = name
                keywords_cache[k] = kws
                added += 1
                print(f"  added {name!r} for key: {k[:80]}")
                break
        else:
            print(f"  NO RULE for key: {k[:100]}")
    if added == 0:
        print("No progress — stopping.")
        break
    save_ai_cache(cache)
    save_ai_keywords_cache(keywords_cache)
else:
    print("Did not converge in 5 rounds.")

print(f"Cache now has {len(cache)} entries")
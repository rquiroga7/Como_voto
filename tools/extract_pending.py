"""Extract the exact to_generate list that generate_ai_names_for_groups would use."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from como_voto_generator.ai_names import (
    _slugs_for_group,
    _strip_section_suffix,
    cache_key,
    load_ai_cache,
)
from como_voto_generator.data_loading import load_all_votaciones_from_db
from como_voto_generator.laws import build_law_groups


def _votacion_sort_key(votacion: dict) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", votacion.get("date", ""))
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return "0000-00-00"


all_votaciones: list[dict] = []
all_votaciones.extend(load_all_votaciones_from_db("diputados"))
all_votaciones.extend(load_all_votaciones_from_db("senadores"))
all_votaciones.sort(key=_votacion_sort_key)
print(f"Loaded {len(all_votaciones)} votaciones", file=sys.stderr)

law_groups = build_law_groups(all_votaciones)
cache = load_ai_cache()

from como_voto_generator.ai_names import AI_NAMES_CACHE_PATH

out = []
seen_keys = set()
for group in law_groups.values():
    if group.get("common_name"):
        continue
    title = (group.get("title") or "").strip()
    if len(title) < 10:
        continue
    base_title = _strip_section_suffix(title)
    if len(base_title) < 10:
        base_title = title
    k = cache_key(base_title)
    if k in cache or cache_key(title) in cache:
        continue
    if k in seen_keys:
        continue
    seen_keys.add(k)
    out.append(
        {
            "k": k,
            "base_title": base_title,
            "full_title": title,
            "slug_hint": _slugs_for_group(group, {}),
            "ids": [v.get("id") for v in group.get("votaciones", [])[:6]],
        }
    )

print(f"{len(out)} pending", file=sys.stderr)
Path("pending_titles.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
)
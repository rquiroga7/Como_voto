"""AI-based law name generation with local caching.

Provides short (≤6 word) Spanish titles for Argentine law voting records
that are not covered by the hardcoded COMMON_LAW_NAMES list in laws.py.

Cache file: data/ai_law_names.json  (normalized_title -> short_name)

Environment variables:
  OPENAI_API_KEY   – required for generation (any OpenAI-compatible key)
  OPENAI_BASE_URL  – optional override (default: https://api.openai.com/v1)
  AI_MODEL         – optional model override (default: gpt-4o-mini)
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path

from .common import DATA_DIR, log

AI_NAMES_CACHE_PATH = DATA_DIR / "ai_law_names.json"
AI_KEYWORDS_CACHE_PATH = DATA_DIR / "ai_law_keywords.json"

_SYSTEM_PROMPT = (
    "Sos un experto en legislación argentina con amplio conocimiento de cómo los medios "
    "y la opinión pública denominan las leyes.\n"
    "Tu tarea es proporcionar el nombre corto más conocido de una ley, más palabras clave "
    "para búsqueda.\n"
    "Prioridad para el nombre:\n"
    "1. Si la ley tiene un nombre popular o mediático bien establecido en Argentina "
    "(como 'Ley de Alquileres', 'Ficha Limpia', 'IVE', 'Ley Ómnibus', 'RIGI', etc.), usá ese nombre.\n"
    "2. Si no tiene nombre popular, generá un nombre descriptivo conciso.\n"
    "3. IMPORTANTE - Tipos procedimentales: Si el título describe una moción o procedimiento parlamentario "
    "('Apartamiento de Reglamento', 'Moción de Orden', 'Moción de Reconsideración', "
    "'Habilitación del tratamiento', 'Tratamiento sobre tablas', etc.), el nombre DEBE empezar con ese tipo procedimental "
    "y NUNCA con 'Ley'. Ejemplos correctos: 'Apartamiento de Reglamento Ferraro', "
    "'Moción de Orden Soria', 'Habilitación tratamiento tablas'.\n"
    "4. IMPORTANTE - Declaraciones y resoluciones: Si el título es un 'Proyecto de Declaración', "
    "'Proyecto de Resolución', 'Beneplácito', 'Homenaje', 'Declaración de interés', 'Fiesta Nacional', "
    "'Día Nacional', etc., NO es una ley. El nombre DEBE empezar con 'Declaración', 'Beneplácito', "
    "'Resolución' o similar y NUNCA con 'Ley'. Ejemplos: 'Declaración Beneplácito Pello', 'Resolución Convocatoria Ministro'.\n"
    "5. IMPORTANTE - Designaciones y acuerdos: Si el título es un 'Acuerdo para designar', 'Pliego', "
    "'Designación', 'Propuesta de designación', 'Ascenso', 'Nombramiento' de jueces, fiscales, embajadores, "
    "miembros de fuerzas armadas, etc., NO es una ley. El nombre DEBE empezar con 'Acuerdo', 'Pliego', "
    "'Designación', 'Ascenso' y NUNCA con 'Ley'. Ejemplos: 'Acuerdo Designación Juez', 'Pliego Embajador Oxenford', "
    "'Ascenso Militares'.\n"
    "6. IMPORTANTE - Tratados y convenios: Si el título es aprobación de un tratado, convenio o acuerdo internacional, "
    "el nombre debe reflejar el acuerdo (ej. 'Acuerdo con Chile', 'Convenio FONPLATA') y puede empezar con 'Acuerdo' "
    "o 'Convenio', no necesariamente 'Ley'.\n"
    "7. IMPORTANTE - Temas Varios: Si el título es genérico 'Temas Varios O.D. ...' sin descripción de ley específica, "
    "el nombre debe ser 'Temas Varios' o similar, NUNCA inventes 'Ley de ...'.\n"
    "8. IMPORTANTE - Múltiples votaciones por artículos/capítulos: Si el título contiene referencia a capítulo, artículo, "
    "título o inciso específico (ej. 'Artículo 11', 'Cap. 2 Art. 12 al Art. 15', 'Título IX'), el nombre debe ser el de "
    "la LEY COMPLETA, sin mencionar el artículo/capítulo. Ejemplo: para 'Presupuesto Ejercicio Fiscal 2004 ** Artículo 11' "
    "el nombre correcto es 'Presupuesto 2004', NO 'Presupuesto Artículo 11'. Para 'Exp. 57 - S - 04 * O.D. 764 * "
    "Capítulo 1 * Art. 2 al Art. 9. Régimen Federal de Responsabilidad Fiscal' el nombre es "
    "'Régimen Federal de Responsabilidad Fiscal'.\n"
    "Respondé ÚNICAMENTE con JSON válido en este formato exacto:\n"
    '{"name": "nombre corto", "keywords": ["kw1", "kw2"]}\n'
    "Reglas:\n"
    "- name: máximo 6 palabras en español\n"
    "- keywords: hasta 5 términos de búsqueda alternativos (siglas, nombres populares, "
    "tema principal, sinónimos), en minúsculas. Incluí términos que la gente usaría para "
    "buscar esta ley aunque no estén en el nombre corto."
)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def cache_key(title: str) -> str:
    """Normalize a title for use as a cache key (same as COMMON_NORM)."""
    return (
        unicodedata.normalize("NFKD", title or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


def _strip_section_suffix(title: str) -> str:
    """Strip En General/Particular and Capítulo/Título/Artículo suffixes.

    Mirrors como_voto_generator.laws._strip_section_suffix but kept here
    to avoid circular imports. Must stay in sync.
    """
    if not title:
        return title
    t = title.strip()
    t = re.sub(r"\s*[-–—]+\s*En\s+General\s*\.?\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*[-–—]+\s*En\s+Particular\s*\.?\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*Votaci[oó]n\s+en\s+General\s*\.?\s*$", "", t, flags=re.I)
    # Middle " - Artículo 8. Presupuestos..." -> " - Presupuestos..."
    t = re.sub(
        r"\s*[-–—*]+\s*Art(?:\.|iculo)?s?\s*[0-9°ºNro\.\s]+(?:\s*(?:al|a|y|,)\s*[0-9°º]+)?\s*\.\s*",
        " - ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s*[-–—*]+\s*Cap(?:\.|itulo)?\s*[IVXLCDM0-9]+\s*[-–—*]*\s*", " ", t, flags=re.I)
    t = re.sub(r"\s*[-–—*]+\s*T[íi]tulo\s*[IVXLCDM0-9]+\s*[-–—*]*\s*", " ", t, flags=re.I)
    # Trailing to end - handle "10o", "10º", "10", roman numerals, etc.
    t = re.sub(
        r"\s*[-–—*]+\s*(?:Art(?:\.|iculo)?s?|Cap(?:\.|itulo)?|T[íi]tulo)\s*[IVXLCDM0-9°ºoa]+(?:\s*(?:al|a|y|,)\s*[IVXLCDM0-9°ºoa]+)*\s*\.?\s*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s*\*+\s*Art(?:\.|iculo)?s?\s*[0-9°ºoa]+.*$", "", t, flags=re.I)
    t = re.sub(
        r"\s*[-–—]+\s*T[íi]tulo\s+[IVXLCDM0-9]+\s*[-–—]+\s*Art(?:\.|iculo)?s?\s*[0-9°ºoa]+.*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip(" -–—*.,")
    t = re.sub(r"\s*-\s*-\s*", " - ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def base_cache_key(title: str) -> str:
    """Normalized key for base law title (without section suffix)."""
    return cache_key(_strip_section_suffix(title))


def load_ai_cache() -> dict[str, str]:
    """Load the AI names cache from disk. Returns empty dict if not present."""
    if AI_NAMES_CACHE_PATH.exists():
        try:
            with open(AI_NAMES_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            log.warning(f"Could not read AI names cache: {exc}")
    return {}


def save_ai_cache(cache: dict[str, str]) -> None:
    """Save the AI names cache to disk atomically."""
    AI_NAMES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = AI_NAMES_CACHE_PATH.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, AI_NAMES_CACHE_PATH)
    except Exception as exc:
        log.exception(f"Failed to save AI names cache: {exc}")


def load_ai_keywords_cache() -> dict[str, list[str]]:
    """Load the AI keywords cache from disk. Returns empty dict if not present."""
    if AI_KEYWORDS_CACHE_PATH.exists():
        try:
            with open(AI_KEYWORDS_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            log.warning(f"Could not read AI keywords cache: {exc}")
    return {}


def save_ai_keywords_cache(cache: dict[str, list[str]]) -> None:
    """Save the AI keywords cache to disk atomically."""
    AI_KEYWORDS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = AI_KEYWORDS_CACHE_PATH.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, AI_KEYWORDS_CACHE_PATH)
    except Exception as exc:
        log.exception(f"Failed to save AI keywords cache: {exc}")


def get_cached_ai_name(title: str, cache: dict[str, str]) -> str | None:
    """Look up a title in the AI cache. Returns None if not found."""
    return cache.get(cache_key(title)) or None


# ---------------------------------------------------------------------------
# Slug hint helpers
# ---------------------------------------------------------------------------

def slug_to_hint(slug: str) -> str:
    """Convert an HCDN URL slug into a readable hint string.

    e.g. 'ley-ficha-limpia-voto-general' -> 'ley ficha limpia voto general'
    """
    return slug.replace("-", " ").replace(".", "").strip()


def _slugs_for_group(group: dict, slug_map: dict[str, str]) -> str:
    """Return a deduplicated readable hint built from the slugs of a group's
    Diputados votaciones, or an empty string if none are available."""
    seen: set[str] = set()
    parts: list[str] = []
    for v in group.get("votaciones", []):
        if v.get("chamber") != "diputados":
            continue
        slug = slug_map.get(str(v.get("id", "")))
        if not slug:
            continue
        hint = slug_to_hint(slug)
        if hint not in seen:
            seen.add(hint)
            parts.append(hint)
        if len(parts) >= 3:  # cap at 3 slugs to avoid noise
            break
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _call_ai_api(title: str, slug_hint: str = "") -> tuple[str, list[str]]:
    """Call an OpenAI-compatible API to generate a short law name and keywords.

    Args:
        title: The full bureaucratic title of the law.
        slug_hint: Optional readable hint derived from HCDN URL slugs.

    Returns:
        (short_name, keywords) tuple.

    Raises ValueError if OPENAI_API_KEY is not set.
    Raises requests.HTTPError on API errors.
    """
    import requests

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it to use AI name generation."
        )

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")

    user_msg = f"Título completo: {title}\n"
    if slug_hint:
        user_msg += f"Palabras clave del slug URL: {slug_hint}\n"

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 250,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    try:
        data = json.loads(content)
        name = str(data.get("name", "")).strip()
        # Strip characters that aren't ASCII printable or common Spanish diacritics
        name = re.sub(r"[^\x20-\x7EáéíóúüñÁÉÍÓÚÜÑ¿¡ºª]", "", name).strip()
        keywords = [
            str(k).lower().strip()
            for k in data.get("keywords", [])
            if k and str(k).strip()
        ]
        if not name:
            raise ValueError("empty name in JSON response")
        return name, keywords[:5]
    except (json.JSONDecodeError, ValueError, KeyError):
        # Fallback: treat raw content as the name with no keywords
        clean = re.sub(r"[^\x20-\x7EáéíóúüñÁÉÍÓÚÜÑ¿¡ºª]", "", content).strip()
        return clean[:80], []


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def _load_slug_map() -> dict[str, str]:
    """Load the HCDN slug map from cache without triggering a network update."""
    slug_map_path = DATA_DIR / "hcdn_slug_map.json"
    if slug_map_path.exists():
        try:
            with open(slug_map_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def generate_ai_names_for_groups(
    law_groups: dict,
    *,
    skip_existing: bool = True,
    delay: float = 0.3,
    save_every: int = 10,
) -> dict[str, str]:
    """Generate AI names for law groups that lack a common_name.

    Args:
        law_groups: dict as returned by build_law_groups().
        skip_existing: if True (default), skip groups that already have
            a hardcoded common_name.
        delay: seconds to wait between API calls (avoid rate limits).
        save_every: persist cache to disk every N successful generations.

    Returns:
        The updated cache dict.
    """
    cache = load_ai_cache()
    slug_map = _load_slug_map()

    # Collect unique (title, slug_hint) pairs that need generation
    seen_keys: set[str] = set()
    to_generate: list[tuple[str, str]] = []  # (title, slug_hint)

    for group in law_groups.values():
        if skip_existing and group.get("common_name"):
            continue
        title = (group.get("title") or "").strip()
        if len(title) < 10:
            continue
        # Use base title without En General/Capítulo/Artículo so all
        # votaciones of the same law share one AI name
        base_title = _strip_section_suffix(title)
        if len(base_title) < 10:
            base_title = title
        k = cache_key(base_title)
        # Also check original full title key for backward compatibility
        if k in cache or cache_key(title) in cache:
            continue
        if k in seen_keys:
            continue
        seen_keys.add(k)
        slug_hint = _slugs_for_group(group, slug_map)
        to_generate.append((base_title, slug_hint))

    if not to_generate:
        log.info("AI names: cache is up to date, nothing to generate.")
        return cache

    # If no API key is configured, skip generation entirely to avoid
    # spamming 196 warnings and wasting ~60s on daily runs.
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        log.warning(
            f"AI names: OPENAI_API_KEY not set — skipping generation of {len(to_generate)} titles "
            f"(cache remains {len(cache)} entries). Set secret to enable."
        )
        return cache

    log.info(f"AI names: generating {len(to_generate)} new titles…")
    keywords_cache = load_ai_keywords_cache()
    succeeded = 0
    failed = 0

    for i, (title, slug_hint) in enumerate(to_generate, 1):
        k = cache_key(title)
        try:
            name, keywords = _call_ai_api(title, slug_hint)
            cache[k] = name
            if keywords:
                keywords_cache[k] = keywords
            hint_display = f" [slug: {slug_hint[:40]}]" if slug_hint else ""
            kw_display = f" kw={keywords}" if keywords else ""
            log.info(f"[{i}/{len(to_generate)}] {title[:60]!r}{hint_display} → {name!r}{kw_display}")
            succeeded += 1
            if succeeded % save_every == 0:
                save_ai_cache(cache)
                save_ai_keywords_cache(keywords_cache)
        except Exception as exc:
            log.warning(f"[{i}/{len(to_generate)}] Failed for {title[:70]!r}: {exc}")
            failed += 1

        if i < len(to_generate):
            time.sleep(delay)

    save_ai_cache(cache)
    save_ai_keywords_cache(keywords_cache)
    log.info(
        f"AI names: done. {succeeded} generated, {failed} failed, "
        f"{len(cache)} total in cache."
    )
    return cache

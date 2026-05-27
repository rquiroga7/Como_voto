from __future__ import annotations

import json
import re
import unicodedata

from .common import DATA_DIR, log

# ---------------------------------------------------------------------------
# Party classification for law-search breakdown
# ---------------------------------------------------------------------------
# Unlike classify_bloc() (PJ/PRO/LLA/OTHER coalitions used for alignment
# tracking), this classifies into the five actual major parties by their
# real bloc name at the time of voting.

# Exact phrases that must NOT match PJ keywords (checked before _PJ_PARTY_KW)
_OTROS_OVERRIDE_PHRASES = [
    "peronismo federal",
]

_PJ_PARTY_KW = [
    "justicialista",
    "frente de todos",
    "frente para la victoria",
    "unión por la patria",
    "union por la patria",
    "frente renovador",
    "peronismo",
    "peronista",
    "frente cívico por santiago",
    "frente civico por santiago",
    "movimiento popular neuquino",
    "pj ",
    "pj frente",
    "unidad ciudadana",
    "frente nacional y popular",
]
_UCR_PARTY_KW = [
    "ucr",
    "unión cívica radical",
    "union civica radical",
    "radical",
    "evolución radical",
    "evolucion radical",
    "democracia para siempre",
]
_PRO_PARTY_KW = [
    "propuesta republicana",
    "union pro",
    "unión pro",
    "frente pro",
    "cambiemos",
    "juntos por el cambio",
]
_LLA_PARTY_KW = ["la libertad avanza", "libertad avanza"]
_CC_PARTY_KW = ["coalición cívica", "coalicion civica", "a.r.i"]

_PRO_WORD_RE = re.compile(r"\bpro\b")

# ---------------------------------------------------------------------------
# Bloc -> coalition mapping (for legislator alignment tracking)
# ---------------------------------------------------------------------------
_BLOC_COALITION_MAP: dict[str, str] | None = None

_PJ_COALITION_KW = [
    "justicialista",
    "frente de todos",
    "frente para la victoria",
    "unión por la patria",
    "union por la patria",
    "frente renovador",
    "peronismo",
    "peronista",
    "frente cívico por santiago",
    "frente civico por santiago",
    "movimiento popular neuquino",
    "bloque justicialista",
    "pj ",
]
_PRO_COALITION_KW = [
    "pro ",
    "propuesta republicana",
    "cambiemos",
    "juntos por el cambio",
    "juntos por el cambio federal",
    "ucr",
    "unión cívica radical",
    "union civica radical",
    "coalición cívica",
    "coalicion civica",
    "evolución radical",
    "evolucion radical",
]
_LLA_COALITION_KW = [
    "la libertad avanza",
]


def load_bloc_coalition_map() -> dict[str, str]:
    """Load bloc->coalition map from JSON, caching results in memory."""
    global _BLOC_COALITION_MAP
    if _BLOC_COALITION_MAP is not None:
        return _BLOC_COALITION_MAP

    map_path = DATA_DIR / "bloc_coalition_map.json"
    if not map_path.exists():
        log.warning("bloc_coalition_map.json not found - using keyword fallback")
        _BLOC_COALITION_MAP = {}
        return _BLOC_COALITION_MAP

    try:
        with open(map_path, "r", encoding="utf-8") as handle:
            _BLOC_COALITION_MAP = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Failed to load bloc_coalition_map.json: {exc}")
        _BLOC_COALITION_MAP = {}
        return _BLOC_COALITION_MAP

    log.info(f"Loaded bloc coalition map with {len(_BLOC_COALITION_MAP)} entries")
    return _BLOC_COALITION_MAP


def _load_bloc_coalition_map() -> dict[str, str]:
    """Backward-compatible alias for callers using the old helper name."""
    return load_bloc_coalition_map()


def _classify_bloc_coalition_fallback(bloc_name: str) -> str:
    """Keyword fallback used when a bloc is missing from the mapping file."""
    name = bloc_name.lower().strip()
    for keyword in _PJ_COALITION_KW:
        if keyword in name:
            return "PJ"
    for keyword in _PRO_COALITION_KW:
        if keyword in name:
            return "PRO"
    for keyword in _LLA_COALITION_KW:
        if keyword in name:
            return "LLA"
    return "OTROS"


def classify_bloc_mapped(bloc_name: str) -> str:
    """Classify bloc names using the full mapping with keyword fallback."""
    mapping = load_bloc_coalition_map()
    key = bloc_name.lower().strip()
    if key in mapping:
        return mapping[key]
    return _classify_bloc_coalition_fallback(bloc_name)

# Regex helpers for extracting section labels from votación titles
_REF_SUFFIX_RE = re.compile(
    r"\.?(?:PE|CD|JGM|S)-\d+/\d+(?:-[A-Z]+)?[,.]?\s*O\.?\s*D\.?\s*\d+/\d+[,.]?\s*$",
    re.IGNORECASE,
)
_OD_SUFFIX_RE = re.compile(r"[.,]?\s*O\.?\s*D\.?\s*\d+/\d+[,.]?\s*$", re.IGNORECASE)
_OD_PREFIX_RE = re.compile(
    r"^(?:VOTACI[OÓ]N:?\s*)?(?:O\.?\s*D\.?\s*\d+\s*[-–—]\s*)?",
    re.IGNORECASE,
)
_EXP_PREFIX_RE = re.compile(
    r"^(?:EXP(?:EDIENTE)?\.?\s*\S+\s*[-–—]\s*(?:O\.?\s*D\.?\s*\d+\s*[-–—]\s*)?)?",
    re.IGNORECASE,
)
_DICT_RE = re.compile(r"\bDICT\.\s*DE\s*(?:MAY|MIN)\.?\s*", re.IGNORECASE)
_EN_GRAL_RE = re.compile(r"(?:VOT\.?\s*)?EN\s+G(?:ENERAL|RAL)\.?", re.IGNORECASE)
_TITULO_RE = re.compile(r"T[IÍ]TULO\s+([IVXLCDM]+|\d+)", re.IGNORECASE)
_CAPITULO_RE = re.compile(r"CAP[IÍ]?(?:TULO)?[.\s]\s*([IVXLCDM]+|\d+)", re.IGNORECASE)
_ARTICULO_RE = re.compile(
    r"ARTS?[IÍ]?(?:CULOS?)?[.\s°º]\s*(\d+(?:\s*[°º])?)"
    r"(?:\s*(?:AL?|Y|,)\s*(\d+(?:\s*[°º])?))?",
    re.IGNORECASE,
)
_INCISO_RE = re.compile(r"INCISOS?\s+([A-Z](?:\s*(?:AL|Y|,)\s*[A-Z])*)", re.IGNORECASE)


def _clean_votacion_title(title: str) -> str:
    """Elimina ruido de un título de votación para extraer su sección."""
    cleaned = title.strip()
    cleaned = _REF_SUFFIX_RE.sub("", cleaned)
    cleaned = _OD_SUFFIX_RE.sub("", cleaned)
    cleaned = _OD_PREFIX_RE.sub("", cleaned)
    cleaned = _EXP_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(
        r"^Orden\s+del\s+D[ií]a\s+\d+\s*[-–—.]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _DICT_RE.sub("", cleaned)
    return cleaned.strip(" .,")


def extract_section_label(title: str, vtype: str = "") -> str:
    """Extrae una etiqueta descriptiva de sección desde un título de votación."""
    cleaned = _clean_votacion_title(title)

    parts: list[str] = []
    for match in _TITULO_RE.finditer(cleaned):
        parts.append(f"Título {match.group(1)}")
    for match in _CAPITULO_RE.finditer(cleaned):
        parts.append(f"Cap. {match.group(1)}")
    for match in _ARTICULO_RE.finditer(cleaned):
        n1 = match.group(1).replace("°", "").replace("º", "").strip()
        if match.group(2):
            n2 = match.group(2).replace("°", "").replace("º", "").strip()
            parts.append(f"Arts. {n1} a {n2}")
        else:
            parts.append(f"Art. {n1}")
    for match in _INCISO_RE.finditer(cleaned):
        parts.append(f"Inc. {match.group(1)}")

    if parts:
        seen: set[str] = set()
        unique: list[str] = []
        for part in parts:
            if part not in seen:
                seen.add(part)
                unique.append(part)
        return ", ".join(unique)

    # Only check for En General / En Particular if no specific section was found
    if _EN_GRAL_RE.search(cleaned) or "EN GENERAL" in vtype.upper():
        return "En General"

    if re.search(r"en\s+particular", cleaned, re.IGNORECASE):
        return "En Particular"

    vtype_clean = vtype.strip()
    if vtype_clean:
        upper_vtype = vtype_clean.upper()
        if "EN PARTICULAR" in upper_vtype:
            return "En Particular"
        if "EN GENERAL" in upper_vtype:
            return "En General"
        return vtype_clean
    return ""


def classify_bloc_party(bloc_name: str) -> str:
    """Clasifica un bloque en uno de cinco partidos reales u OTROS."""
    name = bloc_name.lower().strip()
    for phrase in _OTROS_OVERRIDE_PHRASES:
        if phrase in name:
            return "OTROS"
    for keyword in _PJ_PARTY_KW:
        if keyword in name:
            return "PJ"
    for keyword in _UCR_PARTY_KW:
        if keyword in name:
            return "UCR"
    if _PRO_WORD_RE.search(name):
        return "PRO"
    for keyword in _PRO_PARTY_KW:
        if keyword in name:
            return "PRO"
    for keyword in _LLA_PARTY_KW:
        if keyword in name:
            return "LLA"
    for keyword in _CC_PARTY_KW:
        if keyword in name:
            return "CC"
    return "OTROS"


# ---------------------------------------------------------------------------
# Province name normalization
# ---------------------------------------------------------------------------
_PROVINCE_CANONICAL: dict[str, str] = {
    "buenos aires": "Buenos Aires",
    "c.a.b.a.": "CABA",
    "capital federal": "CABA",
    "ciudad autonoma de buenos aires": "CABA",
    "ciudad autónoma de buenos aires": "CABA",
    "catamarca": "Catamarca",
    "chaco": "Chaco",
    "chubut": "Chubut",
    "corrientes": "Corrientes",
    "cordoba": "Córdoba",
    "córdoba": "Córdoba",
    "entre rios": "Entre Ríos",
    "entre ríos": "Entre Ríos",
    "formosa": "Formosa",
    "jujuy": "Jujuy",
    "la pampa": "La Pampa",
    "la rioja": "La Rioja",
    "mendoza": "Mendoza",
    "misiones": "Misiones",
    "neuquen": "Neuquén",
    "neuquén": "Neuquén",
    "rio negro": "Río Negro",
    "río negro": "Río Negro",
    "salta": "Salta",
    "san juan": "San Juan",
    "san luis": "San Luis",
    "santa cruz": "Santa Cruz",
    "santa fe": "Santa Fe",
    "santiago del estero": "Santiago del Estero",
    "tierra del fuego": "Tierra del Fuego",
    "tierra del fuego, antartida e islas del atlantico sur": "Tierra del Fuego",
    "tierra del fuego, antártida e islas del atlántico sur": "Tierra del Fuego",
    "tucuman": "Tucumán",
    "tucumán": "Tucumán",
}


def normalize_province(province: str) -> str:
    """Devuelve el nombre canónico de provincia con mayúsculas iniciales."""
    key = unicodedata.normalize("NFC", province.strip().lower())
    return _PROVINCE_CANONICAL.get(key, province.strip())


def normalize_vote(vote_str: str) -> str:
    vote = vote_str.upper().strip()
    if "AFIRMATIV" in vote:
        return "AFIRMATIVO"
    if "NEGATIV" in vote:
        return "NEGATIVO"
    if "ABSTENCI" in vote:
        return "ABSTENCION"
    if "AUSENT" in vote:
        return "AUSENTE"
    if "PRESIDEN" in vote:
        return "PRESIDENTE"
    if not vote:
        # Empty string: no vote recorded (walked out, unregistered, etc.) → AUSENTE
        return "AUSENTE"
    return vote


def normalize_name(name: str) -> str:
    # Remove nicknames in quotes (e.g., "TOPO", "PIPI")
    normalized = re.sub(r'\s*"[^"]*"', '', name.strip())
    normalized = re.sub(r"\s+", " ", normalized).upper()
    replacements = {
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
        "Ü": "U",
        "Ñ": "N",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


# ---------------------------------------------------------------------------
# Name alias map: normalized alias -> normalized canonical name.
# ---------------------------------------------------------------------------
NAME_ALIASES: dict[str, str] = {
    "AGUNDEZ, JORGE ALFRESO": "AGUNDEZ, JORGE ALFREDO",
    "LOPEZ, JUAN CARLOS.": "LOPEZ, JUAN CARLOS",
    "AGUIRRE, HILDA": "AGUIRRE, HILDA CLELIA",
    "AVELIN DE GINESTAR, NANCY B.": "AVELIN DE GINESTAR, NANCY",
    "BASUALDO, ROBERTO": "BASUALDO, ROBERTO GUSTAVO",
    "COBOS, JULIO": "COBOS, JULIO CESAR CLETO",
    "CORNEJO, ALFREDO": "CORNEJO, ALFREDO VICTOR",
    "FELLNER, LILIANA": "FELLNER, LILIANA BEATRIZ",
    "FERNANDEZ DE KIRCHNER, CRISTINA E.": "FERNANDEZ DE KIRCHNER, CRISTINA",
    "FILMUS, DANIEL": "FILMUS, DANIEL FERNANDO",
    "GONZALEZ, PABLO G.": "GONZALEZ, PABLO GERARDO",
    "MARQUEZ, NADIA": "MARQUEZ, NADIA JUDITH",
    "MARTINEZ, ALFREDO": "MARTINEZ, ALFREDO ANSELMO",
    "MENEM, EDUARDO": "MENEM, EDUARDO ADRIAN",
    "MIRABELLA, ROBERTO": "MIRABELLA, ROBERTO MARIO",
    "MONTENEGRO, GUILLERMO": "MONTENEGRO, GUILLERMO TRISTAN",
    "PARRILLI, OSCAR ISIDRO": "PARRILLI, OSCAR ISIDRO JOSE",
    "RITONDO, CRISTIAN A.": "RITONDO, CRISTIAN",
    "SANTILLI, DIEGO": "SANTILLI, DIEGO CESAR",
    "SNOPEK, GUILLERMO": "SNOPEK, GUILLERMO EUGENIO MARIO",
    "SORIA, MARTIN": "SORIA, MARTIN IGNACIO",
    "TAIANA, JORGE": "TAIANA, JORGE ENRIQUE",
    "TERRAGNO, RODOLFO": "TERRAGNO, RODOLFO HECTOR",
}

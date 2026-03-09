#!/usr/bin/env python3
"""
Como Voto - Data Processor / Site Generator
============================================
Reads scraped voting data from consolidated JSON files in data/
and generates aggregated JSON files for the interactive frontend
(docs/data/ directory for GitHub Pages).

Features:
  - Reads compact consolidated DB (one file per chamber)
  - Cross-chamber name matching (legislators in both Diputados & Senadores)
  - Law grouping (EN GENERAL + EN PARTICULAR articles -> single law)
  - Common law name mapping
  - Waffle visualization data output
  - Contested-only alignment calculation
"""

from __future__ import annotations

import json
import os
import re
import sys
import logging
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import time

# Import ConsolidatedDB and helpers from scraper
from scraper import ConsolidatedDB, classify_bloc, VOTE_DECODE, PJ_KEYWORDS, LLA_KEYWORDS

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"
FOTOS_DIR = DOCS_DIR / "fotos"

# ---------------------------------------------------------------------------
# Bloc → coalition mapping (loaded from data/bloc_coalition_map.json)
# Built by build_bloc_map.py using Wikipedia party/alliance data.
# Used to classify legislators by the party they were ELECTED with,
# not the bloc they most recently belong to.
# ---------------------------------------------------------------------------
_BLOC_COALITION_MAP: dict[str, str] | None = None


def _load_bloc_coalition_map() -> dict[str, str]:
    """Load the bloc→coalition mapping from JSON, or return empty dict."""
    global _BLOC_COALITION_MAP
    if _BLOC_COALITION_MAP is not None:
        return _BLOC_COALITION_MAP
    map_path = DATA_DIR / "bloc_coalition_map.json"
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            _BLOC_COALITION_MAP = json.load(f)
        log.info(f"Loaded bloc coalition map with {len(_BLOC_COALITION_MAP)} entries")
    else:
        log.warning("bloc_coalition_map.json not found — run build_bloc_map.py first")
        _BLOC_COALITION_MAP = {}
    return _BLOC_COALITION_MAP


def classify_bloc_mapped(bloc_name: str) -> str:
    """Classify a bloc name using the comprehensive mapping.

    Falls back to the keyword-based classify_bloc() from scraper.py
    if the mapping doesn't have an entry for this bloc.
    """
    mapping = _load_bloc_coalition_map()
    key = bloc_name.lower().strip()
    if key in mapping:
        return mapping[key]
    return classify_bloc(bloc_name)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("processor")


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
    "justicialista", "frente de todos", "frente para la victoria",
    "unión por la patria", "union por la patria",
    "frente renovador", "peronismo", "peronista",
    "frente cívico por santiago", "frente civico por santiago",
    "movimiento popular neuquino", "pj ", "pj frente",
    "unidad ciudadana", "frente nacional y popular",
]
_UCR_PARTY_KW = [
    "ucr", "unión cívica radical", "union civica radical",
    "radical", "evolución radical", "evolucion radical",
    "democracia para siempre",
]
_PRO_PARTY_KW = [
    "propuesta republicana", "union pro", "unión pro",
    "frente pro", "cambiemos", "juntos por el cambio",
]
_LLA_PARTY_KW = ["la libertad avanza", "libertad avanza"]
_CC_PARTY_KW = ["coalición cívica", "coalicion civica", "a.r.i"]

_PRO_WORD_RE = re.compile(r"\bpro\b")

# Regex helpers for extracting section labels from votación titles
# Senado reference suffixes: use known code prefixes (PE, CD, JGM, S)
# to avoid eating roman numerals concatenated before them
_REF_SUFFIX_RE = re.compile(
    r'\.?(?:PE|CD|JGM|S)-\d+/\d+(?:-[A-Z]+)?[,.]?\s*O\.?\s*D\.?\s*\d+/\d+[,.]?\s*$',
    re.IGNORECASE,
)
_OD_SUFFIX_RE = re.compile(r'[.,]?\s*O\.?\s*D\.?\s*\d+/\d+[,.]?\s*$', re.IGNORECASE)
_OD_PREFIX_RE = re.compile(
    r'^(?:VOTACI[OÓ]N:?\s*)?(?:O\.?\s*D\.?\s*\d+\s*[-–—]\s*)?',
    re.IGNORECASE,
)
_EXP_PREFIX_RE = re.compile(
    r'^(?:EXP(?:EDIENTE)?\.?\s*\S+\s*[-–—]\s*'
    r'(?:O\.?\s*D\.?\s*\d+\s*[-–—]\s*)?)?',
    re.IGNORECASE,
)
_DICT_RE = re.compile(r'\bDICT\.\s*DE\s*(?:MAY|MIN)\.?\s*', re.IGNORECASE)
_EN_GRAL_RE = re.compile(
    r'(?:VOT\.?\s*)?EN\s+G(?:ENERAL|RAL)\.?', re.IGNORECASE
)
_TITULO_RE = re.compile(r'T[IÍ]TULO\s+([IVXLCDM]+|\d+)', re.IGNORECASE)
_CAPITULO_RE = re.compile(
    r'CAP[IÍ]?(?:TULO)?[.\s]\s*([IVXLCDM]+|\d+)', re.IGNORECASE
)
_ARTICULO_RE = re.compile(
    r'ARTS?[IÍ]?(?:CULOS?)?[.\s°º]\s*(\d+(?:\s*[°º])?)'
    r'(?:\s*(?:AL?|Y|,)\s*(\d+(?:\s*[°º])?))?',
    re.IGNORECASE,
)
_INCISO_RE = re.compile(
    r'INCISOS?\s+([A-Z](?:\s*(?:AL|Y|,)\s*[A-Z])*)', re.IGNORECASE
)


def _clean_votacion_title(title: str) -> str:
    """Strip noise from a votación title for section extraction."""
    s = title.strip()
    # Strip Senado reference suffixes (PE-159/25-PL,O.D. 699/2025)
    s = _REF_SUFFIX_RE.sub('', s)
    # Strip standalone O.D. NNN/NNNN at end
    s = _OD_SUFFIX_RE.sub('', s)
    # Strip Diputados O.D. N - prefix
    s = _OD_PREFIX_RE.sub('', s)
    # Strip Exp. / Expediente prefix
    s = _EXP_PREFIX_RE.sub('', s)
    # Strip 'Orden del Día NNN -' prefix
    s = re.sub(r'^Orden\s+del\s+D[ií]a\s+\d+\s*[-–—.]\s*',
               '', s, flags=re.IGNORECASE)
    # Strip DICT. DE MAY.
    s = _DICT_RE.sub('', s)
    return s.strip(' .,')


def extract_section_label(title: str, vtype: str = "") -> str:
    """Extract a descriptive section label from a votación title.

    Returns labels like 'En General', 'Título I', 'Título V, Cap. II,
    Arts. 87 a 91', etc.  Falls back to *vtype* or empty string.
    """
    cleaned = _clean_votacion_title(title)

    # En General
    if _EN_GRAL_RE.search(cleaned) or 'EN GENERAL' in vtype.upper():
        return 'En General'

    parts: list[str] = []
    for m in _TITULO_RE.finditer(cleaned):
        parts.append(f'Título {m.group(1)}')
    for m in _CAPITULO_RE.finditer(cleaned):
        parts.append(f'Cap. {m.group(1)}')
    for m in _ARTICULO_RE.finditer(cleaned):
        n1 = m.group(1).replace('°', '').replace('º', '').strip()
        if m.group(2):
            n2 = m.group(2).replace('°', '').replace('º', '').strip()
            parts.append(f'Arts. {n1} a {n2}')
        else:
            parts.append(f'Art. {n1}')
    for m in _INCISO_RE.finditer(cleaned):
        parts.append(f'Inc. {m.group(1)}')

    if parts:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return ', '.join(unique)

    # Fallback: detect 'en particular' in title text
    if re.search(r'en\s+particular', cleaned, re.IGNORECASE):
        return 'En Particular'

    # Fallback to vtype (normalise case)
    vtype_clean = vtype.strip()
    if vtype_clean:
        vu = vtype_clean.upper()
        if 'EN PARTICULAR' in vu:
            return 'En Particular'
        if 'EN GENERAL' in vu:
            return 'En General'
        return vtype_clean
    return ''


def classify_bloc_party(bloc_name: str) -> str:
    """Classify a bloc name into one of five real parties or OTHER.

    Returns one of: PJ, UCR, PRO, LLA, CC, OTHER.
    """
    name = bloc_name.lower().strip()
    for phrase in _OTROS_OVERRIDE_PHRASES:
        if phrase in name:
            return "OTROS"
    for kw in _PJ_PARTY_KW:
        if kw in name:
            return "PJ"
    for kw in _UCR_PARTY_KW:
        if kw in name:
            return "UCR"
    if _PRO_WORD_RE.search(name):
        return "PRO"
    for kw in _PRO_PARTY_KW:
        if kw in name:
            return "PRO"
    for kw in _LLA_PARTY_KW:
        if kw in name:
            return "LLA"
    for kw in _CC_PARTY_KW:
        if kw in name:
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
    """Return the canonical Title-Case province name."""
    key = unicodedata.normalize("NFC", province.strip().lower())
    return _PROVINCE_CANONICAL.get(key, province.strip())


# ---------------------------------------------------------------------------
# Common law names mapping
# ---------------------------------------------------------------------------
COMMON_LAW_NAMES = [
        # --- Major 2023-2024+ laws ---
        (['bases y puntos de partida', "ley de bases", "ley bases"],
         "Ley Bases"),
        (["medidas fiscales paliativas", "paquete fiscal"],
         "Paquete Fiscal"),
        (["régimen de incentivo para grandes inversiones",
            "regimen de incentivo para grandes inversiones", "rigi"],
         "RIGI"),
        (["decreto de necesidad y urgencia 70", "dnu 70"],
         "DNU 70/2023"),

        # --- Economy & taxes ---
        (["impuesto a las ganancias"], "Impuesto a las Ganancias"),
        (["bienes personales"], "Bienes Personales"),
        (["presupuesto general", "presupuesto de la administración",
            "presupuesto de la administracion", "ley de presupuesto"],
         "Presupuesto"),
        (["movilidad jubilatoria", "movilidad previsional"],
         "Movilidad Jubilatoria"),
        (["régimen previsional", "regimen previsional"],
         "Regimen Previsional"),
        (["privatización", "privatizacion"], "Privatizaciones"),
        (["deuda externa", "reestructuración de deuda",
            "reestructuracion de deuda"], "Deuda Externa"),
        (["monotributo", "régimen simplificado para pequeños contribuyentes",
            "regimen simplificado para pequeños contribuyentes"],
         "Monotributo"),
        (["consenso fiscal"], "Consenso Fiscal"),
        (["fondo monetario internacional", "fondo monetario"],
         "FMI"),
        (["derechos de exportación", "derechos de exportacion",
            "retenciones agropecuarias"],
         "Retenciones / Derechos de Exportacion"),

        # --- Electoral & institutional ---
        (["boleta única", "boleta unica"], "Boleta Unica de Papel"),
        (["ficha limpia"], "Ficha Limpia"),
        (["régimen electoral", "regimen electoral",
            "código electoral", "codigo electoral"],
         "Regimen Electoral"),
        (["paridad de género", "paridad de genero"],
         "Paridad de Genero"),
        (["consejo de la magistratura"], "Consejo de la Magistratura"),

        # --- Codes ---
        (["código procesal penal", "codigo procesal penal"],
         "Codigo Procesal Penal"),
        (["código penal", "codigo penal"], "Codigo Penal"),
        (["código civil", "codigo civil"], "Codigo Civil"),
        (["código aduanero", "codigo aduanero"], "Codigo Aduanero"),

        # --- Justice & security ---
        (["juicio en ausencia"], "Juicio en Ausencia"),
        (["régimen penal juvenil", "penal juvenil"],
         "Regimen Penal Juvenil"),
        (["lavado de activos"], "Lavado de Activos"),
        (["extinción de dominio", "extincion de dominio"],
         "Extincion de Dominio"),
        (["inteligencia nacional", "agencia federal de inteligencia"],
         "Inteligencia Nacional"),
        (["narcotráfico", "narcotrafico"], "Narcotráfico"),

        # --- Labor ---
        (["reforma laboral", "modernización laboral",
            "modernizacion laboral"], "Reforma Laboral"),
        (["teletrabajo"], "Teletrabajo"),
        (["trabajo agrario"], "Trabajo Agrario"),

        # --- Housing & property ---
        (["ley de alquileres", "locaciones urbanas"],
         "Ley de Alquileres"),
        (["tierras rurales", "dominio nacional sobre la propiedad"],
         "Tierras Rurales"),

        # --- Social & rights ---
        (["interrupción voluntaria del embarazo",
            "interrupcion voluntaria del embarazo", "aborto"],
         "IVE / Aborto"),
        (["violencia de género", "violencia de genero"],
         "Violencia de Género"),
        (["emergencia alimentaria"], "Emergencia Alimentaria"),
        (["matrimonio igualitario",
            "matrimonio entre personas del mismo sexo",
            "matrimonio civil",
            "código civil, sobre matrimonio",
            "codigo civil, sobre matrimonio"],
         "Matrimonio Igualitario"),
        (["identidad de género", "identidad de genero",
            "ley de identidad",
            "cd-76/11"],   # Temas Varios O.D.CD-76/11-PL,O.D. 62/2012 — Senate 09/05/2012 (Ley 26.743)
         "Ley de Identidad de Género"),
        (["cupo laboral trans", "cupo laboral travesti",
            "acceso al empleo formal para personas travestis",
            "acceso al empleo formal para pers travestis",
            "travesti, transexual", "travestis, transexuales"],
         "Cupo Laboral Trans"),
        (["salud mental"], "Salud Mental"),
        (["barrios populares"], "Barrios Populares"),

        # --- Education & science ---
        (["financiamiento universitario"], "Financiamiento Universitario"),
        (["educación sexual", "educacion sexual"], "Educacion Sexual"),
        (["financiamiento de la ciencia",
            "financiamiento científico", "financiamiento cientifico",
            "ciencia, tecnología e innovación",
            "ciencia, tecnologia e innovacion",
            "ciencia y tecnología", "ciencia y tecnologia"],
         "Financiamiento Cientifico"),

        # --- Health ---
        (["cannabis medicinal", "uso medicinal de la planta de cannabis"],
         "Cannabis Medicinal"),
        (["cadena de frío de los medicamentos",
            "cadena de frio de los medicamentos",
            "producción pública de medicamentos",
            "produccion publica de medicamentos"],
         "Ley de Medicamentos"),

        # --- Environment ---
        (["etiquetado frontal"], "Etiquetado Frontal"),
        (["humedales"], "Ley de Humedales"),
        (["manejo del fuego"], "Manejo del Fuego"),
        (["glaciares"], "Ley de Glaciares"),
        (["energías renovables", "energias renovables",
            "fuentes renovables de energía",
            "fuentes renovables de energia",
            "energía renovable", "energia renovable"],
         "Energias Renovables"),

        # --- Consumer & commerce ---
        (["góndolas", "gondolas"], "Ley de Gondolas"),
        (["economía del conocimiento", "economia del conocimiento"],
         "Economia del Conocimiento"),
        (["compre argentino", "compre nacional"], "Compre Argentino"),

        # --- Media & communication ---
        (["servicios de comunicación audiovisual",
            "servicios de comunicacion audiovisual", "ley de medios"],
         "Ley de Medios"),

        # --- Transparency ---
        (["acceso a la información pública",
            "acceso a la informacion publica"],
         "Acceso a Info. Publica"),

        # --- Transport & safety ---
        (["seguridad vial", "tránsito y seguridad vial",
            "transito y seguridad vial"],
         "Seguridad Vial"),
        (["ludopatía", "ludopatia", "apuestas en línea",
            "apuestas en linea", "juegos de azar y apuestas"],
         "Ludopatia / Apuestas Online"),

        # --- Other ---
        (["defensa nacional"], "Defensa Nacional"),
        (["inocencia fiscal"], "Inocencia Fiscal"),
]


def COMMON_NORM(s: str) -> str:
        return unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii').lower()


# Precompute normalized keywords per rule so we don't re-normalize on
# every call to get_common_name.
_COMMON_LAW_RULES: list[tuple[list[str], str]] = []
for _keywords, _common_name in COMMON_LAW_NAMES:
        _COMMON_LAW_RULES.append(
                ([COMMON_NORM(kw) for kw in _keywords], _common_name)
        )


def _kw_matches(kw_norm: str, t_norm: str) -> bool:
        """Return True if *kw_norm* is found inside *t_norm*.

        Short tokens (<=4 chars) require a whole-word boundary match to
        avoid accidental substring hits; longer phrases use plain substring
        matching which is more forgiving with punctuation.
        """
        if len(kw_norm) <= 4:
                return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", t_norm))
        return kw_norm in t_norm


def get_common_name(title: str) -> str | None:
        """Return the best-matching common law name for *title*, or None.

        Every rule in COMMON_LAW_NAMES is evaluated against the title.
        For each rule we count how many of its keywords match and sum
        their lengths.  The rule with the highest score wins — scored by
        ``(total_matched_keyword_length, matched_token_count)`` — which
        avoids ambiguous first-match-wins behaviour and ensures more
        specific rules beat shorter / vaguer ones.
        """
        if not title:
                return None
        t_norm = COMMON_NORM(title)

        best_name: str | None = None
        best_score: tuple[int, int] = (0, 0)

        for norm_keywords, common_name in _COMMON_LAW_RULES:
                matched_length = 0
                matched_count = 0
                for kw_norm in norm_keywords:
                        if _kw_matches(kw_norm, t_norm):
                                matched_length += len(kw_norm)
                                matched_count += 1

                if matched_count > 0:
                        score = (matched_length, matched_count)
                        if score > best_score:
                                best_score = score
                                best_name = common_name

        return best_name


# ---------------------------------------------------------------------------
# Law grouping
# ---------------------------------------------------------------------------

def extract_law_group_key(votacion: dict) -> str:
    title = votacion.get("title", "")
    date = votacion.get("date", "")
    chamber = votacion.get("chamber", "")

    date_part = ""
    dm = re.search(r"(\d{2}/\d{2}/\d{4})", date)
    if dm:
        date_part = dm.group(1)

    # Extract O.D. / C.D. numbers
    od_match = re.search(
        r"(O\.?\s*D\.?\s*N?[°ºo]?\s*\d+(?:/\d+)?)", title, re.IGNORECASE
    )
    if od_match:
        od_num = re.sub(r"\s+", "", od_match.group(1).upper())
        return f"{chamber}|{od_num}|{date_part}"

    exp_match = re.search(
        r"(Exp(?:ediente)?\.?\s*N?[°ºo]?\s*[\d\-]+(?:/\d+)?)",
        title, re.IGNORECASE
    )
    if exp_match:
        exp_num = re.sub(r"\s+", "", exp_match.group(1).upper())
        return f"{chamber}|{exp_num}|{date_part}"

    # Strip vote-type markers to group related votes
    clean = title.upper()
    clean = re.sub(r"\s*-?\s*EN\s+(GENERAL|PARTICULAR)\s*", " ", clean)
    clean = re.sub(r"\s*-?\s*ART[IÍ]?CULO?\s+\d+.*", "", clean)
    clean = re.sub(r"\s*-?\s*ART\.?\s+\d+.*", "", clean)
    clean = re.sub(
        r"\s*-?\s*MODIFICACIONES?\s+(AL|DEL)\s+SENADO.*", "", clean
    )
    clean = re.sub(r"\s+", " ", clean).strip()

    if len(clean) > 15:
        return f"{chamber}|{clean[:100]}|{date_part}"

    return f"{chamber}|SINGLE|{votacion.get('id', '')}"


def build_law_groups(all_votaciones: list[dict]) -> dict:
    groups = defaultdict(lambda: {
        "votaciones": [], "title": "", "date": "",
        "common_name": None, "chamber": "",
    })

    for v in all_votaciones:
        key = extract_law_group_key(v)
        g = groups[key]
        g["votaciones"].append(v)
        if len(v.get("title", "")) > len(g["title"]):
            g["title"] = v.get("title", "")
        if not g["date"]:
            g["date"] = v.get("date", "")
        g["chamber"] = v.get("chamber", "")

    for key, g in groups.items():
        cn = get_common_name(g["title"])
        if cn:
            g["common_name"] = cn

    return dict(groups)


# ---------------------------------------------------------------------------
# Data loading (from consolidated JSON)
# ---------------------------------------------------------------------------

def load_all_votaciones_from_db(chamber: str) -> list[dict]:
    """Load all votaciones from a consolidated DB file, expanding them
    to the full format used by the rest of the pipeline."""
    db_path = DATA_DIR / f"{chamber}.json"
    if not db_path.exists():
        log.warning(f"Consolidated DB not found: {db_path}")
        return []

    db = ConsolidatedDB(db_path)
    db.load()
    log.info(f"Loaded {len(db.votaciones)} {chamber} votaciones from DB")
    return db.expand_all(chamber)


def clean_date(date_str: str) -> str:
    """Clean date string: extract DD/MM/YYYY and optional HH:MM."""
    m = re.search(r"(\d{2}/\d{2}/\d{4})", date_str)
    if not m:
        return date_str.strip()
    result = m.group(1)
    time_m = re.search(r"(\d{2}:\d{2})", date_str)
    if time_m:
        result += " - " + time_m.group(1)
    return result


def extract_year(date_str: str) -> int | None:
    match = re.search(r"(\d{4})", date_str)
    if match:
        return int(match.group(1))
    return None


def practical_year_range(years_list: list[str]) -> tuple[str | None, str | None]:
    """Return (min_year, max_year) ignoring isolated early outliers.

    If the earliest year has a gap > 10 years before the next year (e.g.
    a single 1983 vote before continuous coverage starting in 2005) the
    isolated year is skipped so the display range is more accurate.
    """
    if not years_list:
        return None, None
    ints = sorted(int(y) for y in years_list)
    start = ints[0]
    if len(ints) > 1 and (ints[1] - ints[0]) > 10:
        start = ints[1]
    return str(start), str(ints[-1])


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def compute_majority_vote(votes: list[dict], coalition: str) -> str:
    def _norm(s: str) -> str:
        return unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii').upper()

    coalition_up = _norm(coalition) if coalition else coalition
    wanted = {coalition_up} if coalition_up else set()
    coalition_votes = []
    for v in votes:
        coal = classify_bloc_mapped(v.get("bloc", ""))
        coal_up = _norm(coal)
        bloc_up = _norm(v.get("bloc", ""))
        if coal_up in wanted or any(w in bloc_up for w in wanted):
            coalition_votes.append(v)
    if not coalition_votes:
        return "N/A"

    counts = defaultdict(int)
    for v in coalition_votes:
        vote = v["vote"].upper()
        if "AFIRMATIV" in vote:
            counts["AFIRMATIVO"] += 1
        elif "NEGATIV" in vote:
            counts["NEGATIVO"] += 1
        elif "ABSTENCI" in vote or "ABSTENCION" in vote:
            counts["ABSTENCION"] += 1
        elif "AUSENT" in vote:
            counts["AUSENTE"] += 1

    active_counts = {k: v for k, v in counts.items() if k != "AUSENTE"}
    if not active_counts:
        return "AUSENTE"

    return max(active_counts, key=active_counts.get)


def compute_combined_majority(
    votes: list[dict], coalitions: list[str]
) -> str:
    """Compute majority vote across multiple coalitions combined.
    Used for 2023+ opposition bloc (LLA + PRO grouped together).
    """
    def _norm(s: str) -> str:
        return unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii').upper()

    wanted = set(_norm(c) for c in coalitions)
    coalition_votes = []
    for v in votes:
        coal = classify_bloc_mapped(v.get("bloc", ""))
        coal_up = _norm(coal)
        bloc_up = _norm(v.get("bloc", ""))
        if coal_up in wanted or any(w in bloc_up for w in wanted):
            coalition_votes.append(v)
    if not coalition_votes:
        return "N/A"

    counts = defaultdict(int)
    for v in coalition_votes:
        vote = v["vote"].upper()
        if "AFIRMATIV" in vote:
            counts["AFIRMATIVO"] += 1
        elif "NEGATIV" in vote:
            counts["NEGATIVO"] += 1
        elif "ABSTENCI" in vote or "ABSTENCION" in vote:
            counts["ABSTENCION"] += 1
        elif "AUSENT" in vote:
            counts["AUSENTE"] += 1

    active_counts = {k: v for k, v in counts.items() if k != "AUSENTE"}
    if not active_counts:
        return "AUSENTE"

    return max(active_counts, key=active_counts.get)


def is_contested(year: int | None, pj_majority: str, opp_majority: str) -> bool:
    """Return True when a votación is contested between PJ and the
    dynamically selected opposition majority for that year.

    Excludes cases where either side has no active majority ('N/A') or
    only 'AUSENTE'.
    """
    if year is None:
        return False
    if pj_majority in ("N/A", "AUSENTE"):
        return False
    if opp_majority in ("N/A", "AUSENTE"):
        return False
    return pj_majority != opp_majority


def normalize_vote(vote_str: str) -> str:
    v = vote_str.upper().strip()
    if "AFIRMATIV" in v:
        return "AFIRMATIVO"
    elif "NEGATIV" in v:
        return "NEGATIVO"
    elif "ABSTENCI" in v:
        return "ABSTENCION"
    elif "AUSENT" in v:
        return "AUSENTE"
    elif "PRESIDEN" in v:
        return "PRESIDENTE"
    return v


def _parse_vote_date(d: str) -> datetime:
    """Parse a vote date string (DD/MM/YYYY - HH:MM) into a datetime."""
    d = d.strip()
    try:
        return datetime.strptime(d, "%d/%m/%Y - %H:%M")
    except (ValueError, AttributeError):
        try:
            return datetime.strptime(d[:10], "%d/%m/%Y")
        except (ValueError, AttributeError):
            return datetime.min


def _count_trailing_ausente(votes: list[dict]) -> int:
    """Count AUSENTE votes that occur after the legislator's last active vote.

    When a legislator leaves office (death, resignation, appointment to
    another role), they stop attending votes but remain on the chamber
    roster.  All votes after their last attendance are recorded as AUSENTE.
    These trailing absences should not count against their presentismo.
    """
    if not votes:
        return 0
    non_ausente = [v for v in votes if v.get("v") != "AUSENTE"]
    if not non_ausente:
        return 0  # Never attended — don't exclude anything
    last_active_dt = max(_parse_vote_date(v.get("d", "")) for v in non_ausente)
    trailing = sum(
        1 for v in votes
        if v.get("v") == "AUSENTE" and _parse_vote_date(v.get("d", "")) > last_active_dt
    )
    return trailing


def normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip().upper())
    replacements = {
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "Ü": "U", "Ñ": "N",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name


# ---------------------------------------------------------------------------
# Name alias map: normalized alias → normalized canonical name.
# Used to merge duplicate legislator records that arise from the same person
# being recorded under slightly different name variants across sources/time.
# Keys and values are in normalize_name() form (stripped accents, uppercase).
# ---------------------------------------------------------------------------
NAME_ALIASES: dict[str, str] = {
    # Typos in source data
    "AGUNDEZ, JORGE ALFRESO":              "AGUNDEZ, JORGE ALFREDO",
    "LOPEZ, JUAN CARLOS.":                 "LOPEZ, JUAN CARLOS",
    # Short / abbreviated name → full name (same person, different sources)
    "AGUIRRE, HILDA":                      "AGUIRRE, HILDA CLELIA",
    "AVELIN DE GINESTAR, NANCY B.":        "AVELIN DE GINESTAR, NANCY",
    "BASUALDO, ROBERTO":                   "BASUALDO, ROBERTO GUSTAVO",
    "COBOS, JULIO":                        "COBOS, JULIO CESAR CLETO",
    "CORNEJO, ALFREDO":                    "CORNEJO, ALFREDO VICTOR",
    "FELLNER, LILIANA":                    "FELLNER, LILIANA BEATRIZ",
    "FERNANDEZ DE KIRCHNER, CRISTINA E.":  "FERNANDEZ DE KIRCHNER, CRISTINA",
    "FILMUS, DANIEL":                      "FILMUS, DANIEL FERNANDO",
    "GONZALEZ, PABLO G.":                  "GONZALEZ, PABLO GERARDO",
    "MARQUEZ, NADIA":                      "MARQUEZ, NADIA JUDITH",
    "MARTINEZ, ALFREDO":                   "MARTINEZ, ALFREDO ANSELMO",
    "MENEM, EDUARDO":                      "MENEM, EDUARDO ADRIAN",
    "MIRABELLA, ROBERTO":                  "MIRABELLA, ROBERTO MARIO",
    "MONTENEGRO, GUILLERMO":               "MONTENEGRO, GUILLERMO TRISTAN",
    "PARRILLI, OSCAR ISIDRO":              "PARRILLI, OSCAR ISIDRO JOSE",
    "RITONDO, CRISTIAN A.":                "RITONDO, CRISTIAN",
    "SANTILLI, DIEGO":                     "SANTILLI, DIEGO CESAR",
    "SNOPEK, GUILLERMO":                   "SNOPEK, GUILLERMO EUGENIO MARIO",
    "SORIA, MARTIN":                       "SORIA, MARTIN IGNACIO",
    "TAIANA, JORGE":                       "TAIANA, JORGE ENRIQUE",
    "TERRAGNO, RODOLFO":                   "TERRAGNO, RODOLFO HECTOR",
}


def load_photo_maps() -> dict[str, str]:
    """Load photo name->filename mappings from scraper output.
    Returns a dict: normalized_name -> relative path (fotos/filename).
    """
    photo_map: dict[str, str] = {}

    # Diputados photos
    dip_photos_path = DATA_DIR / "diputados_photos.json"
    if dip_photos_path.exists():
        try:
            with open(dip_photos_path, "r", encoding="utf-8") as f:
                dip_photos = json.load(f)
            for name, filename in dip_photos.items():
                nk = normalize_name(name)
                photo_map[nk] = f"fotos/{filename}"
        except (json.JSONDecodeError, OSError):
            pass

    # Senadores photos
    sen_photos_path = DATA_DIR / "senadores_photos.json"
    if sen_photos_path.exists():
        try:
            with open(sen_photos_path, "r", encoding="utf-8") as f:
                sen_photos = json.load(f)
            for name, filename in sen_photos.items():
                nk = normalize_name(name)
                if nk not in photo_map:
                    photo_map[nk] = f"fotos/{filename}"
        except (json.JSONDecodeError, OSError):
            pass

    # Also scan the consolidated DB for photo_ids
    dip_db_path = DATA_DIR / "diputados.json"
    if dip_db_path.exists():
        db = ConsolidatedDB(dip_db_path)
        db.load()
        for ni_str, photo_id in db.photo_ids.items():
            ni = int(ni_str)
            if ni < len(db.names):
                name = db.names[ni]
                nk = normalize_name(name)
                filename = f"fotos/dip_{photo_id}.jpg"
                if nk not in photo_map:
                    photo_map[nk] = filename

    # Propagate photos across aliases: if the canonical key has no photo but
    # its alias does (or vice-versa), copy it over so merged records get a photo.
    for alias_key, canon_key in NAME_ALIASES.items():
        if canon_key not in photo_map and alias_key in photo_map:
            photo_map[canon_key] = photo_map[alias_key]

    return photo_map


def attach_photos(legislators: dict, photo_map: dict[str, str]):
    """Attach photo paths to legislator records."""
    matched = 0
    for name_key, leg in legislators.items():
        photo = photo_map.get(name_key, "")
        if photo:
            full_path = DOCS_DIR / photo.replace("/", os.sep)
            if full_path.exists():
                leg["photo"] = photo
                matched += 1
            else:
                leg["photo"] = ""
        else:
            leg["photo"] = ""
    log.info(f"Attached photos to {matched}/{len(legislators)} legislators")


def _article_from_slug(url: str) -> str | None:
    """Extract an article/section label from an HCDN slug URL.

    HCDN appends the vote-type descriptor at the END of the slug, e.g.:
      …/votacion/derecho-identidad-genero-articulo-5/394  -> "Art. 5"
      …/votacion/ley-bases-titulo-ii/394                  -> "Título II"
      …/votacion/ley-bases-en-particular/394              -> "En Particular"

    Returns None when no EN-PARTICULAR pattern is found so the title/vtype
    fallback still handles EN-GENERAL cases (avoiding false positives).
    """
    m = re.search(r'/votacion/([^/]+)/\d+$', url)
    if not m:
        return None
    slug = m.group(1).lower()

    # -articulo-{N[suffix]} at end (most common EN PARTICULAR pattern)
    art = re.search(r'-articulo-(\d+[a-z]*)$', slug)
    if art:
        return f"Art. {art.group(1)}"

    # -titulo-{roman/digits} at end
    tit = re.search(r'-titulo-([ivxlcdm\d]+(?:-[a-z]+)?)$', slug)
    if tit:
        return f"T\u00edtulo {tit.group(1).upper()}"

    # -en-particular at end (no specific article number)
    if slug.endswith('-en-particular') or slug.endswith('-particular'):
        return "En Particular"

    return None


def build_legislator_data(
    all_votaciones: list[dict], law_groups: dict
) -> dict:
    legislators = {}

    votacion_to_group = {}
    for group_key, group_data in law_groups.items():
        for v in group_data["votaciones"]:
            vid = f"{v.get('chamber', '')}_{v.get('id', '')}"
            votacion_to_group[vid] = group_key

    for votacion in all_votaciones:
        year = extract_year(votacion.get("date", ""))
        votacion_id = votacion.get("id", "")
        chamber = votacion.get("chamber", "")
        title = votacion.get("title", "")
        date = clean_date(votacion.get("date", ""))
        vtype = votacion.get("type", "")

        vid_key = f"{chamber}_{votacion_id}"
        group_key = votacion_to_group.get(vid_key, "")
        group_data = law_groups.get(group_key, {})
        law_display_name = (
            group_data.get("common_name")
            or group_data.get("title", title)
        )

        # Coalition definitions (case-insensitive matching)
        PJ_COALITIONS = [
            "PJ", "JUSTICIALISTAS", "FRENTE PARA LA VICTORIA",
            "FRENTE DE TODOS", "UNION POR LA PATRIA", "UXP", "Unidad Ciudadana", "Frente Justicialista"
        ]
        UCR_COALITIONS = [
            "UCR", "UNION CIVICA RADICAL", "UNIÓN CÍVICA RADICAL", "RADICAL",
            "CC", "ACyS", "UDESO", "FPCyS", "Frente Progresista Cívico y Social",
            "Unión para el Desarrollo Social", "Acuerdo Cívico y Social",
            "Concertación para Una Nación Avanzada", "UNA", "ARI",
            "Argentinos por una República de Iguales", "Coalición Cívica",
            "Coalición Cívica ARI"
        ]
        JXC_COALITIONS = ["UCR", "Unión Cívica Radical", "Union Civica Radical","JxC", "Juntos por el Cambio", "CC", "Coalición Cívica" "Cambiemos", "PRO", "Propuesta Republicana", "Frente Pro", "Frente Cambiemos", "Frente Juntos por el Cambio", "ARI", "Coalición Cívica ARI"]
        LLA_PRO_COALITIONS = ["LLA", "PRO", "Juntos por el Cambio", "Alianza La Libertad Avanza"]

        # PJ majority across the PJ coalition variants
        pj_majority = compute_combined_majority(votacion.get("votes", []), PJ_COALITIONS)

        combined_ucr = compute_combined_majority(votacion.get("votes", []), UCR_COALITIONS)
        combined_jxc = compute_combined_majority(votacion.get("votes", []), JXC_COALITIONS)
        combined_lla_pro = compute_combined_majority(votacion.get("votes", []), LLA_PRO_COALITIONS)

        # choose opposition majority based on year
        if year is None:
            opp_majority = "N/A"
        elif year <= 2014:
            opp_majority = combined_ucr
        elif year <= 2023:
            opp_majority = combined_jxc
        else:
            opp_majority = combined_lla_pro

        # Exclude procedural votes
        title_low = title.lower() if title else ""
        if "moción de orden" in title_low or "moción del diputado" in title_low or "mocion de orden" in title_low or "pedido de licencia" in title_low or "pedido de pref" in title_low or "apartamiento del reglamento solicitado" in title_low or "pedido tratamiento sobre tablas" in title_low:
            contested = False
        else:
            contested = is_contested(year, pj_majority, opp_majority)

        for vote_record in votacion.get("votes", []):
            name = vote_record.get("name", "").strip()
            if not name:
                continue

            name_key = normalize_name(name)
            name_key = NAME_ALIASES.get(name_key, name_key)  # resolve alias → canonical

            if name_key not in legislators:
                entry_bloc = vote_record.get("bloc", "")
                legislators[name_key] = {
                    "name": name,
                    "name_key": name_key,
                    "chambers": [chamber],
                    "chamber": chamber,
                    "bloc": entry_bloc,
                    "province": normalize_province(vote_record.get("province", "")),

                    "coalition": classify_bloc_mapped(entry_bloc),
                    "votes": [],
                    "yearly_stats": {},
                    "_yr_blocs": {},  # {chamber: {year_str: {bloc: count}}} - temp
                    "_yr_provinces": {},  # {chamber: {year_str: {province: count}}} - temp
                    "alignment": {
                        "PJ": {"total": 0, "aligned": 0},
                        "PRO": {"total": 0, "aligned": 0},
                        "LLA": {"total": 0, "aligned": 0},
                        "UCR": {"total": 0, "aligned": 0},
                    },
                    "yearly_alignment": {},
                }

            leg = legislators[name_key]
            # Prefer the canonical name as display name over an alias variant
            if normalize_name(name) == name_key:
                leg["name"] = name
                leg["name_key"] = name_key

            if chamber not in leg["chambers"]:
                leg["chambers"].append(chamber)

            leg["bloc"] = vote_record.get("bloc", leg["bloc"])
            leg["province"] = normalize_province(vote_record.get("province", leg["province"]))
            # Update coalition from the current vote's bloc using the
            # comprehensive mapping.  With chronologically-sorted votaciones,
            # this ends up reflecting the legislator's most recent affiliation.
            leg["coalition"] = classify_bloc_mapped(
                vote_record.get("bloc", leg.get("bloc", ""))
            )
            leg["chamber"] = chamber

            norm_vote = normalize_vote(vote_record.get("vote", ""))

            # Primary: extract from HCDN slug URL — reliable even when the
            # stored vtype/title don't distinguish EN PARTICULAR votes
            # (e.g. all three Identidad de Género IDs share the same title
            # and tp="EN GENERAL" but their slugs encode articulo-5/11).
            article_label = _article_from_slug(votacion.get("url", ""))
            if not article_label:
                title_upper = title.upper()
                titulo_match = re.search(
                    r"T[IÍ]TULO\s+([\dIVXLCDM]+)", title_upper
                )
                if titulo_match:
                    article_label = f"Título {titulo_match.group(1)}"
                elif "EN GENERAL" in title_upper or \
                     vtype.upper() == "EN GENERAL":
                    article_label = "En General"
                elif "EN PARTICULAR" in title_upper or \
                     vtype.upper() == "EN PARTICULAR":
                    art_match = re.search(
                        r"ART[IÍ]?CULO?\s*\.?\s*(\d+)", title, re.IGNORECASE
                    )
                    if art_match:
                        article_label = f"Art. {art_match.group(1)}"
                    else:
                        article_label = "En Particular"

            vote_entry = {
                "vid": votacion_id,
                "ch": chamber,
                "t": title[:200],
                "d": date,
                "yr": year,
                "v": norm_vote,
                "pj": pj_majority,
                # store combined coalition majorities for frontend compatibility
                "pro": combined_jxc,
                "lla": combined_lla_pro,
                "ucr": combined_ucr,
                "tp": vtype,
                "gk": group_key,
                "ln": law_display_name[:120] if law_display_name else "",
                "cn": group_data.get("common_name", ""),
                "al": article_label,
            }
            # include link to original source when available
            vot_url = votacion.get("url")
            if vot_url:
                vote_entry["url"] = vot_url
            leg["votes"].append(vote_entry)

            if year:
                yr_key = str(year)
                if yr_key not in leg["yearly_stats"]:
                    leg["yearly_stats"][yr_key] = {
                        "AFIRMATIVO": 0, "NEGATIVO": 0,
                        "ABSTENCION": 0, "AUSENTE": 0,
                        "PRESIDENTE": 0, "total": 0,
                    }
                leg["yearly_stats"][yr_key][norm_vote] = \
                    leg["yearly_stats"][yr_key].get(norm_vote, 0) + 1
                leg["yearly_stats"][yr_key]["total"] += 1

                # Track bloc counts per (chamber, year) for term computation
                bloc_val = vote_record.get("bloc", "").strip()
                if bloc_val:
                    yr_blocs = leg["_yr_blocs"]
                    if chamber not in yr_blocs:
                        yr_blocs[chamber] = {}
                    if yr_key not in yr_blocs[chamber]:
                        yr_blocs[chamber][yr_key] = {}
                    yr_blocs[chamber][yr_key][bloc_val] = \
                        yr_blocs[chamber][yr_key].get(bloc_val, 0) + 1

                # Track province counts per (chamber, year) for term computation
                prov_val = normalize_province(vote_record.get("province", "").strip())
                if prov_val:
                    yr_provs = leg["_yr_provinces"]
                    if chamber not in yr_provs:
                        yr_provs[chamber] = {}
                    if yr_key not in yr_provs[chamber]:
                        yr_provs[chamber][yr_key] = {}
                    yr_provs[chamber][yr_key][prov_val] = \
                        yr_provs[chamber][yr_key].get(prov_val, 0) + 1

                if yr_key not in leg["yearly_alignment"]:
                    leg["yearly_alignment"][yr_key] = {
                        "PJ": {"total": 0, "aligned": 0},
                        # Track multiple opposition groups for reporting
                        "PRO": {"total": 0, "aligned": 0},
                        "LLA": {"total": 0, "aligned": 0},
                        "UCR": {"total": 0, "aligned": 0},
                        "JxC": {"total": 0, "aligned": 0},
                    }

                if contested and norm_vote not in ("AUSENTE", "PRESIDENTE"):
                    # PJ alignment (combined PJ coalition)
                    if pj_majority not in ("N/A", "AUSENTE"):
                        leg["alignment"]["PJ"]["total"] += 1
                        leg["yearly_alignment"][yr_key]["PJ"]["total"] += 1
                        if norm_vote == pj_majority:
                            leg["alignment"]["PJ"]["aligned"] += 1
                            leg["yearly_alignment"][yr_key]["PJ"]["aligned"] += 1

                    # UCR combined majority
                    if combined_ucr not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["UCR"]["total"] += 1
                        if norm_vote == combined_ucr:
                            leg["yearly_alignment"][yr_key]["UCR"]["aligned"] += 1
                        # increment global UCR totals only for years where UCR is the
                        # designated opposition (<= 2014)
                        if year is not None and year <= 2014:
                            leg["alignment"]["UCR"]["total"] += 1
                            if norm_vote == combined_ucr:
                                leg["alignment"]["UCR"]["aligned"] += 1

                    # JxC combined majority
                    if combined_jxc not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["JxC"]["total"] += 1
                        if norm_vote == combined_jxc:
                            leg["yearly_alignment"][yr_key]["JxC"]["aligned"] += 1

                    # JxC / PRO combined majority (store under PRO for compatibility)
                    # Only count these votes toward overall PRO alignment for years
                    # where JxC/PRO was the designated opposition (2015-2023).
                    if combined_jxc not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["PRO"]["total"] += 1
                        if norm_vote == combined_jxc:
                            leg["yearly_alignment"][yr_key]["PRO"]["aligned"] += 1
                        # increment global PRO totals only for 2015-2023
                        if year is not None and 2015 <= year <= 2023:
                            leg["alignment"]["PRO"]["total"] += 1
                            if norm_vote == combined_jxc:
                                leg["alignment"]["PRO"]["aligned"] += 1

                    # LLA + PRO combined majority (tracked under LLA field too)
                    # Only count these votes toward overall LLA alignment for years
                    # where LLA was the designated opposition (2024+).
                    if combined_lla_pro not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["LLA"]["total"] += 1
                        if norm_vote == combined_lla_pro:
                            leg["yearly_alignment"][yr_key]["LLA"]["aligned"] += 1
                        if year is not None and year >= 2024:
                            leg["alignment"]["LLA"]["total"] += 1
                            if norm_vote == combined_lla_pro:
                                leg["alignment"]["LLA"]["aligned"] += 1

    return legislators


_PARTY_KEYS = ("pj", "ucr", "pro", "lla", "cc", "oth")


def build_law_detail_data(law_groups: dict) -> tuple[list[dict], dict[int, dict]]:
    """Build per-law, per-party vote breakdown for the law-search feature.

    Returns a tuple of:
      - list of law entries for laws_detail.json (tallies only, no names)
      - votes_by_year: {year: {"n": [name_table], "v": {vi: {pk: [[idx,...],...]}}}}
        One entry per year, each with a local name table for small file size.

    Each law entry contains display name, year, chamber and, for every
    votación in the group, compact vote tallies broken down by the five
    major parties (PJ / UCR / PRO / LLA / CC) plus OTHER.
    """
    laws: list[dict] = []
    # Collect all voter name lists keyed by a running votación index.
    # Using a sequential integer keeps the JSON keys short.
    all_vote_names: dict[int, dict[str, list[list[str]]]] = {}
    name_set: set[str] = set()
    votacion_counter = 0

    for gk, group in law_groups.items():
        votaciones_raw = group.get("votaciones", [])
        if not votaciones_raw:
            continue

        display_name = group.get("common_name") or group.get("title", "")
        if not display_name or len(display_name.strip()) < 3:
            continue

        # Determine year from first votación with a date
        year: int | None = None
        chamber = group.get("chamber", "")
        for v in votaciones_raw:
            y = extract_year(v.get("date", ""))
            if y:
                year = y
                break
            if not chamber:
                chamber = v.get("chamber", "")

        vs_out: list[dict] = []
        for v in votaciones_raw:
            votes_list = v.get("votes", [])
            if not votes_list:
                continue

            # Tally votes per real party (not coalition)
            tallies: dict[str, list[int]] = {
                "pj":  [0, 0, 0, 0],   # [afirm, neg, abst, aus]
                "ucr": [0, 0, 0, 0],
                "pro": [0, 0, 0, 0],
                "lla": [0, 0, 0, 0],
                "cc":  [0, 0, 0, 0],
                "oth": [0, 0, 0, 0],
            }
            total = [0, 0, 0, 0]

            VOTE_IDX = {
                "AFIRMATIVO": 0,
                "NEGATIVO": 1,
                "ABSTENCION": 2,
                "AUSENTE": 3,
            }

            # Per-legislator names for voter drill-down
            names: dict[str, list[list[str]]] = {
                pk: [[], [], [], []] for pk in _PARTY_KEYS
            }

            for vr in votes_list:
                vote_str = normalize_vote(vr.get("vote", ""))
                idx = VOTE_IDX.get(vote_str)
                if idx is None:
                    continue  # skip PRESIDENTE and unknowns

                party = classify_bloc_party(vr.get("bloc", ""))
                party_key = party.lower() if party != "OTROS" else "oth"

                tallies[party_key][idx] += 1
                total[idx] += 1

                leg_name = vr.get("name", "").strip()
                if leg_name:
                    # Normalize and resolve aliases so names in the year data
                    # match the legislator index keys exactly, enabling links.
                    norm = normalize_name(leg_name)
                    norm = NAME_ALIASES.get(norm, norm)
                    names[party_key][idx].append(norm)
                    name_set.add(norm)

            # Skip votaciones with zero relevant votes
            if sum(total) == 0:
                continue

            vi = votacion_counter
            votacion_counter += 1
            all_vote_names[vi] = names

            # Determine vote type label
            title_str = v.get("title", "")
            vtype = v.get("type", "")
            tp_label = extract_section_label(title_str, vtype)

            entry: dict = {
                "t": title_str[:200],
                "tp": tp_label,
                "d": clean_date(v.get("date", "")),
                "r": v.get("result", ""),
                "vi": vi,
                "tot": total,
                "pj":  tallies["pj"],
                "ucr": tallies["ucr"],
                "pro": tallies["pro"],
                "lla": tallies["lla"],
                "cc":  tallies["cc"],
                "oth": tallies["oth"],
            }

            vid = v.get("id")
            if vid:
                entry["id"] = vid
            url = v.get("url", "")
            if url:
                entry["url"] = url

            vs_out.append(entry)

        if not vs_out:
            continue

        law_entry: dict = {
            "n": (display_name[:120]).strip(),
            "y": year,
            "ch": chamber,
            "vs": vs_out,
        }
        if group.get("common_name"):
            law_entry["cn"] = group["common_name"]

        laws.append(law_entry)

    # Sort: notable (common_name) first, then by year desc, then by name
    laws.sort(key=lambda x: (
        0 if x.get("cn") else 1,
        -(x.get("y") or 0),
        x.get("n", ""),
    ))

    # Build per-year votes indices.  Each year file gets its own compact
    # name table so files stay small (10-50 KB each instead of one 3.8 MB blob).

    # Map vi -> year so we can bucket votaciones.
    vi_to_year: dict[int, int] = {}
    for law in laws:
        y = law.get("y") or 0
        for v in law.get("vs", []):
            vi = v.get("vi")
            if vi is not None:
                vi_to_year[vi] = y

    # Group vi keys by year
    from collections import defaultdict
    year_vis: dict[int, list[int]] = defaultdict(list)
    for vi, y in vi_to_year.items():
        year_vis[y].append(vi)

    # Build one compact file per year with a local name table
    votes_by_year: dict[int, dict] = {}
    for y, vis in year_vis.items():
        # Collect all names used this year
        year_name_set: set[str] = set()
        for vi in vis:
            pn = all_vote_names.get(vi, {})
            for pk in _PARTY_KEYS:
                for vote_i in range(4):
                    for nm in pn.get(pk, [[], [], [], []])[vote_i]:
                        year_name_set.add(nm)

        year_name_list = sorted(year_name_set)
        local_idx = {n: i for i, n in enumerate(year_name_list)}

        compact_votes: dict[str, dict] = {}
        for vi in vis:
            pn = all_vote_names.get(vi, {})
            compact: dict[str, list[list[int]]] = {}
            for pk in _PARTY_KEYS:
                arrs: list[list[int]] = [[], [], [], []]
                for vote_i in range(4):
                    for nm in pn.get(pk, [[], [], [], []])[vote_i]:
                        arrs[vote_i].append(local_idx[nm])
                if any(arrs[i] for i in range(4)):
                    compact[pk] = arrs
            if compact:
                compact_votes[str(vi)] = compact

        votes_by_year[y] = {"n": year_name_list, "v": compact_votes}

    return laws, votes_by_year


# ---------------------------------------------------------------------------
# Election data lookup for coalition classification
# ---------------------------------------------------------------------------
# Uses scraped Wikipedia election data (data/election_legislators.json)
# to determine each legislator's coalition based on the party/alliance they
# were actually elected under, rather than the bloc they served in.
# ---------------------------------------------------------------------------

_ELECTION_INDEX: dict | None = None  # {(year, norm_province, chamber): [{name_tokens, coalition}]}
_ELECTION_YEARS_SORTED: list[int] = []


def _strip_accents(s: str) -> str:
    """Remove diacritic marks: á→a, ñ→n, etc."""
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if unicodedata.category(c) != 'Mn')


def _normalize_display_name(name: str) -> str:
    """Normalize 'SURNAME, FIRSTNAME' to 'SURNAME, Firstname' format.

    Keeps the surname (before comma) uppercase and title-cases the rest,
    with special handling for particles like 'de', 'del', 'de la'.
    """
    if ',' not in name:
        return name
    surname, _, first = name.partition(',')
    first = first.strip()
    if not first:
        return name
    # Title-case the first name part, preserving particles lowercase
    _PARTICLES = {'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e'}
    words = first.split()
    result = []
    for i, w in enumerate(words):
        if w.lower() in _PARTICLES and i > 0:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    return f"{surname.upper()}, {' '.join(result)}"


# ---------------------------------------------------------------------------
# Bloc name normalization
# ---------------------------------------------------------------------------

_BLOC_PARTICLES = {'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'por',
                   'para', 'en', 'con', 'sin', 'al', 'su'}
_BLOC_ACRONYMS = {
    'PJ', 'UCR', 'PRO', 'ARI', 'GEN', 'UNEN', 'FIT', 'PTS', 'PO', 'MST',
    'MID', 'MODIN', 'FREPASO', 'FORJA', 'UPT', 'SI', 'JSRN',
}
# Restore missing accents on common Spanish words in bloc names
_ACCENT_MAP = {
    'union': 'Unión', 'civica': 'Cívica', 'civico': 'Cívico',
    'produccion': 'Producción', 'producción': 'Producción',
    'coalicion': 'Coalición', 'rio': 'Río',
    'accion': 'Acción', 'concertacion': 'Concertación',
    'integracion': 'Integración', 'renovacion': 'Renovación',
    'innovacion': 'Innovación', 'evolucion': 'Evolución',
    'democratico': 'Democrático', 'democrata': 'Demócrata',
    'autonomia': 'Autonomía', 'educacion': 'Educación',
    'inclusion': 'Inclusión', 'energia': 'Energía',
    'republica': 'República', 'soberania': 'Soberanía',
    'participacion': 'Participación', 'tucuman': 'Tucumán',
    'cordoba': 'Córdoba', 'dialogo': 'Diálogo',
}


def _restore_accents(word: str) -> str:
    """Restore missing accent marks on a word."""
    key = word.lower().rstrip('.,;:')
    suffix = word[len(key):]  # trailing punctuation
    if key in _ACCENT_MAP:
        replacement = _ACCENT_MAP[key]
        # Preserve original case pattern
        if word[0].isupper():
            return replacement + suffix
        return replacement[0].lower() + replacement[1:] + suffix
    return word


def _normalize_bloc_display(name: str) -> str:
    """Normalize bloc name capitalization for display.

    - ALL CAPS strings → title case
    - Spanish particles (de, la, y, por, para…) → lowercase (except at start)
    - Known acronyms (PJ, UCR, PRO…) → uppercase
    - Dotted abbreviations (A.R.I, M.M.T.A.) → uppercase
    - Restore missing accent marks (Union → Unión, etc.)
    - Capitalize after hyphens
    """
    if not name or not name.strip():
        return name

    # Normalize " -x" and "x- " patterns to " - x" for consistency
    name = name.replace(' -', ' - ').replace('- ', ' - ')
    while '  ' in name:
        name = name.replace('  ', ' ')

    # Process each segment separated by " - " independently
    segments = name.split(' - ')
    result_segments = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        letters = [c for c in seg if c.isalpha()]
        if not letters:
            result_segments.append(seg)
            continue

        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)

        # If mostly uppercase, title-case it first
        if upper_ratio > 0.6:
            new_words = []
            for w in seg.split():
                # Dotted abbreviations (e.g., A.R.I, F.I.S.CA.L) → uppercase
                if '.' in w and any(c.isalpha() for c in w):
                    new_words.append(w.upper())
                # Hyphenated words → capitalize each part separately
                elif '-' in w:
                    parts = w.split('-')
                    new_words.append('-'.join(p.capitalize() for p in parts))
                else:
                    new_words.append(w.capitalize())
            seg = ' '.join(new_words)

        words = seg.split()
        for i, w in enumerate(words):
            # Handle hyphenated words: capitalize parts + check acronyms
            if '-' in w and len(w) > 1:
                parts = w.split('-')
                for j, p in enumerate(parts):
                    stripped_p = p.strip('()[].,')
                    if stripped_p.upper() in _BLOC_ACRONYMS:
                        parts[j] = p.upper()
                    elif p and p[0].islower():
                        parts[j] = p.capitalize()
                    parts[j] = _restore_accents(parts[j])
                words[i] = '-'.join(parts)
                continue

            stripped = w.strip('()[].,')
            # Dotted abbreviations → uppercase
            if '.' in stripped and any(c.isalpha() for c in stripped):
                words[i] = w.upper()
            # Known acronyms → always uppercase
            elif stripped.upper() in _BLOC_ACRONYMS:
                words[i] = w.upper()
            # Particles → lowercase except at start of segment
            # (skip for dotted abbreviations like "E.", "DE.")
            elif i > 0 and stripped.lower() in _BLOC_PARTICLES and '.' not in w:
                words[i] = w.lower()

            # Restore accents
            words[i] = _restore_accents(words[i])
        result_segments.append(' '.join(words))

    return ' - '.join(result_segments)


# ---------------------------------------------------------------------------
# Era-based coalition remapping (5-coalition system)
# ---------------------------------------------------------------------------
# Coalition labels by era:
#   PJ / UxP         — PJ across all eras
#   UCR / ARI        — main opposition 1983-2014
#   JxC / PRO / UCR  — Cambiemos/JxC coalition 2015-2023
#   LLA / PRO        — La Libertad Avanza + PRO allies 2024+
#   OTROS            — everything else

def _era_coalition(base_co: str, term_yf: int) -> str:
    """Map a base party classification to the era-appropriate coalition.

    base_co: one of PJ, UCR, PRO, LLA, OTROS
    term_yf: first year of the term
    """
    if base_co == "PJ":
        return "PJ"
    if base_co == "UCR":
        if term_yf < 2015:
            return "UCR"
        if term_yf < 2024:
            return "PRO"
        return "OTROS"
    if base_co == "PRO":
        if term_yf < 2015:
            return "OTROS"  # PRO was a minor party before Cambiemos
        if term_yf < 2024:
            return "PRO"
        return "LLA"
    if base_co == "LLA":
        return "LLA"
    return "OTROS"


# Blocs that changed coalition alignment over time.
# Each entry maps to (cutoff_year, coalition_from_that_year_onwards).
_BLOC_ERA_OVERRIDES: dict[str, list[tuple[int, str]]] = {
}


def _classify_bloc_for_term(bloc_name: str, year: int) -> str:
    """Classify a bloc into a base party for coalition assignment.

    Unlike classify_bloc() (used for alignment benchmarks and keeps UCR
    merged with PRO), this separates UCR from PRO and supports era-aware
    overrides for blocs that changed alignment.

    Returns one of: PJ, UCR, PRO, LLA, OTROS.
    """
    key = bloc_name.lower().strip()

    # Check era-aware overrides first
    if key in _BLOC_ERA_OVERRIDES:
        for cutoff, co in sorted(_BLOC_ERA_OVERRIDES[key], reverse=True):
            if year >= cutoff:
                return co
        # Before the earliest cutoff, fall through to standard classification

    # Check bloc_coalition_map.json
    mapping = _load_bloc_coalition_map()
    if key in mapping:
        co = mapping[key]
        # The map uses the old 4-label system; split PRO into UCR vs PRO
        if co == "PRO":
            for kw in ("ucr", "radical", "coalición cívica", "coalicion civica",
                       "evolución", "evolucion", "democracia para siempre"):
                if kw in key:
                    return "UCR"
            return "PRO"
        return co

    # Keyword-based classification (same as classify_bloc but with UCR split)
    for kw in PJ_KEYWORDS:
        if kw in key:
            return "PJ"
    for kw in ("ucr", "unión cívica radical", "union civica radical",
               "radical", "coalición cívica", "coalicion civica",
               "evolución radical", "evolucion radical"):
        if kw in key:
            return "UCR"
    for kw in ("pro ", "propuesta republicana",
               "cambiemos", "juntos por el cambio"):
        if kw in key:
            return "PRO"
    for kw in LLA_KEYWORDS:
        if kw in key:
            return "LLA"
    return "OTROS"


def _norm_province(prov: str) -> str:
    """Normalize province name for matching between DB and election data."""
    p = _strip_accents(prov.strip()).upper()
    p = p.replace('.', '').replace(',', '')
    if p in ('CABA', 'CAPITAL FEDERAL', 'CIUDAD AUTONOMA DE BUENOS AIRES'):
        return 'CAPITAL FEDERAL'
    return p


def _name_tokens(name: str) -> set[str]:
    """Extract a set of normalized word tokens from any name format.

    Handles both "SURNAME, FIRSTNAME" (DB format) and
    "Firstname Surname" (Wikipedia format).
    """
    n = _strip_accents(name).upper()
    n = n.replace(',', ' ')
    # Remove particles that may or may not appear
    tokens = set(n.split())
    # Remove very short tokens (initials, particles) that cause false matches
    tokens.discard('DE')
    tokens.discard('DEL')
    tokens.discard('LA')
    tokens.discard('LOS')
    tokens.discard('LAS')
    tokens.discard('Y')
    tokens.discard('E')
    tokens.discard('S')
    tokens.discard('J')
    return {t for t in tokens if len(t) > 1}


def _load_election_index():
    """Load election data and build a lookup index for fast matching."""
    global _ELECTION_INDEX, _ELECTION_YEARS_SORTED
    if _ELECTION_INDEX is not None:
        return

    path = DATA_DIR / "election_legislators.json"
    if not path.exists():
        log.warning("election_legislators.json not found — run scrape_elections.py")
        _ELECTION_INDEX = {}
        return

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    _ELECTION_INDEX = {}
    years = set()

    for year_str, data in raw.items():
        year = int(year_str)
        years.add(year)
        for chamber in ("diputados", "senadores"):
            for entry in data.get(chamber, []):
                key = (year, _norm_province(entry["province"]), chamber)
                tokens = _name_tokens(entry["name"])
                if not tokens:
                    continue
                _ELECTION_INDEX.setdefault(key, []).append({
                    "tokens": tokens,
                    "coalition": entry["coalition"],
                    "name": entry["name"],
                    "party_code": entry.get("party_code"),
                    "suplente": entry.get("suplente", False),
                })

    _ELECTION_YEARS_SORTED = sorted(years)
    log.info(f"Loaded election index: {len(raw)} years, "
             f"{sum(len(v) for v in _ELECTION_INDEX.values())} candidates")


def _find_election_year(term_start: int) -> int | None:
    """Find the most recent election year <= term_start.

    Terms typically start 1 year after the election (elected 2023, sworn in 2024).
    """
    _load_election_index()
    best = None
    for ey in _ELECTION_YEARS_SORTED:
        if ey <= term_start:
            best = ey
    return best


def _match_legislator_to_election(
    name_key: str,
    province: str,
    chamber: str,
    election_year: int,
) -> dict | None:
    """Try to match a legislator to election data.

    Returns {"coalition": str, "party_code": str|None} or None if no match.
    """
    _load_election_index()
    if not _ELECTION_INDEX:
        return None

    key = (election_year, _norm_province(province), chamber)
    candidates = _ELECTION_INDEX.get(key, [])
    if not candidates:
        return None

    leg_tokens = _name_tokens(name_key)
    if not leg_tokens:
        return None

    best_score = 0.0
    best_match = None

    for cand in candidates:
        cand_tokens = cand["tokens"]
        shared = leg_tokens & cand_tokens
        if not shared:
            continue
        # Score: Jaccard-like similarity but weighted toward shorter set
        score = len(shared) / min(len(leg_tokens), len(cand_tokens))
        # Prefer titulares over suplentes at the same score
        is_better = (
            score > best_score
            or (score == best_score and best_match and best_match.get("suplente") and not cand.get("suplente"))
        )
        if is_better:
            best_score = score
            best_match = cand

    # Require at least 60% overlap with the shorter name
    if best_score >= 0.6 and best_match:
        return {"coalition": best_match["coalition"], "party_code": best_match.get("party_code")}
    return None


def compute_terms(leg: dict, min_votes: int = 5) -> list[dict]:
    """Derive term records from _yr_blocs + yearly_stats.

    1. Groups consecutive active years (gap ≤ 2) per chamber into runs.
    2. Further splits each run into mandate-length chunks:
         diputados → 4 years, senadores → 6 years.
       A shorter chunk = mandate cut short (resignation, death, etc.).

    Returns list of {ch, yf, yt, b} sorted by year.
    """
    MANDATE_LEN = {"diputados": 4, "senadores": 6}

    yr_blocs     = leg.get("_yr_blocs", {})
    yr_provinces = leg.get("_yr_provinces", {})
    yearly_stats = leg.get("yearly_stats", {})
    terms: list[dict] = []

    for ch, yr_dict in yr_blocs.items():
        max_len = MANDATE_LEN.get(ch, 6)

        # Active years: ≥ min_votes total votes that year
        active = sorted(
            int(y) for y in yr_dict
            if yearly_stats.get(y, {}).get("total", 0) >= min_votes
        )
        if not active:
            continue

        # Split into contiguous runs (gap > 2 = new service period)
        runs: list[list[int]] = []
        cur = [active[0]]
        for y in active[1:]:
            if y - cur[-1] <= 2:
                cur.append(y)
            else:
                runs.append(cur)
                cur = [y]
        runs.append(cur)

        for run in runs:
            # Further split by mandate length.  A mandate of N years starting
            # mid-year spans N+1 calendar years (e.g. diputado elected 2021
            # serves Dec 2021 – Dec 2025 = calendar years 2021-2025).
            i = 0
            while i < len(run):
                boundary = run[i] + max_len
                sub = [y for y in run[i:] if y <= boundary]
                i += len(sub)

                bloc_totals: dict[str, int] = {}
                for y in sub:
                    for bloc, cnt in yr_dict.get(str(y), {}).items():
                        bloc_totals[bloc] = bloc_totals.get(bloc, 0) + cnt
                dominant = max(bloc_totals, key=bloc_totals.get) if bloc_totals else ""

                prov_totals: dict[str, int] = {}
                for y in sub:
                    for prov, cnt in yr_provinces.get(ch, {}).get(str(y), {}).items():
                        prov_totals[prov] = prov_totals.get(prov, 0) + cnt
                dominant_prov = max(prov_totals, key=prov_totals.get) if prov_totals else leg.get("province", "")

                # --- Electoral coalition assignment for this mandate ---
                # 1. Try Wikipedia election data (alliance/coalition)
                election_year = _find_election_year(min(sub))
                name_key = leg.get("name_key", "")
                co_electoral = None
                if election_year:
                    match = _match_legislator_to_election(name_key, dominant_prov, ch, election_year)
                    if match:
                        if match.get("coalition") and match["coalition"] != "OTROS":
                            co_electoral = match["coalition"]
                        elif match.get("party_code") and match["party_code"] != "OTROS":
                            co_electoral = match["party_code"]
                # 2. Fallback: bloc-based mapping
                if not co_electoral:
                    base_co = _classify_bloc_for_term(_normalize_bloc_display(dominant), max(sub))
                    co_electoral = _era_coalition(base_co, max(sub))

                terms.append({
                    "ch": ch,
                    "yf": min(sub),
                    "yt": max(sub),
                    "b": _normalize_bloc_display(dominant),
                    "p": dominant_prov,
                    "co_electoral": co_electoral
                })

    terms.sort(key=lambda t: (t["yf"], t["ch"]))

    # Attach coalition to each term based on its congressional bloc.
    # The bloc reflects the legislator's actual allegiance at term end,
    # which is more reliable than Wikipedia election data (party codes
    # and alliances often conflict with current alignment for legislators
    # who switched blocs mid-term).
    for t in terms:
        base_co = _classify_bloc_for_term(t["b"], t["yt"])
        t["co"] = _era_coalition(base_co, t["yt"])

    return terms


def compute_per_coalition_alignment(
    terms: list[dict],
    yearly_alignment: dict,
    yearly_stats: dict,
    min_total: int = 5,
) -> dict[str, dict]:
    """Compute alignment sums restricted to years within terms of each coalition.

    Returns ``{coalition: {"vpj": N, "vucr": N, "vpro": N, "vlla": N, "tv": N, "b": str}}``.
    Only coalitions the legislator actually served under are included.
    The ``"b"`` field is the most recent bloc name for that coalition.
    """

    # For mandate-level grouping by electoral coalition (for second ranking),
    # use t["co_electoral"] if present, else t["co"].
    co_years: dict[str, set[int]] = {}
    co_bloc: dict[str, str] = {}
    for t in terms:
        co = t.get("co_electoral") or t["co"]
        co_years.setdefault(co, set())
        for y in range(t["yf"], t["yt"] + 1):
            co_years[co].add(y)
        co_bloc[co] = t["b"]

    result: dict[str, dict] = {}
    for co, years in co_years.items():
        sums = {"vpj": 0, "vucr": 0, "vpro": 0, "vlla": 0, "tv": 0}
        has_any = False
        for yr_str, data in yearly_alignment.items():
            try:
                yint = int(yr_str)
            except (ValueError, TypeError):
                continue
            if yint not in years:
                continue
            for coalition, field in [("PJ", "vpj"), ("UCR", "vucr"),
                                     ("PRO", "vpro"), ("LLA", "vlla")]:
                d = data.get(coalition, {})
                tot = d.get("total", 0)
                if tot < min_total:
                    continue
                # Apply same era masks as the global ranking
                if coalition == "UCR" and yint > 2014:
                    continue
                if coalition in ("JxC", "PRO") and not (2015 <= yint <= 2023):
                    continue
                if coalition == "LLA" and yint < 2024:
                    continue
                sums[field] += d.get("aligned", 0)
                has_any = True
        # Sum total votes for those years
        for yr_str, stats in yearly_stats.items():
            try:
                yint = int(yr_str)
            except (ValueError, TypeError):
                continue
            if yint in years:
                sums["tv"] += stats.get("total", 0)
        if has_any or sums["tv"] > 0:
            sums["b"] = _normalize_bloc_display(co_bloc.get(co, ""))
            result[co] = sums
    return result


def compute_weighted_alignment(yearly_alignment: dict, coalition: str, min_total: int = 5) -> float | None:
    """Return overall alignment % as a weighted mean of yearly values.

    Only years that meet ``min_total`` contested votes (under the same year
    masks used for per-year display) are included.  Returns None when no
    year qualifies.
    """
    total_w = 0
    total_aligned = 0
    for yr, data in yearly_alignment.items():
        try:
            yint = int(yr)
        except (ValueError, TypeError):
            continue
        d = data.get(coalition, {})
        tot = d.get("total", 0)
        if tot < min_total:
            continue
        # Apply the same year masks used for per-year display
        if coalition == "UCR":
            if yint > 2014:
                continue
        elif coalition in ("JxC", "PRO"):
            if not (2015 <= yint <= 2023):
                continue
        elif coalition == "LLA":
            if yint < 2024:
                continue
        # PJ: no year mask
        total_w += tot
        total_aligned += d.get("aligned", 0)
    if total_w == 0:
        return None
    return round(total_aligned / total_w * 100, 1)


def compute_era_alignment(
    yearly_alignment: dict,
    coalition: str,
    year_min: int,
    year_max: int,
    min_total: int = 5,
) -> float | None:
    """Weighted alignment % for ``coalition`` restricted to [year_min, year_max].

    Uses raw {total, aligned} counts (from leg["yearly_alignment"]) so the
    result is a true weighted mean: sum(aligned) / sum(total) rather than the
    arithmetic mean of per-year percentages.
    """
    total_w = 0
    total_aligned = 0
    for yr, data in yearly_alignment.items():
        try:
            yint = int(yr)
        except (ValueError, TypeError):
            continue
        if not (year_min <= yint <= year_max):
            continue
        d = data.get(coalition, {})
        tot = d.get("total", 0)
        if tot < 1:
            continue
        total_w += tot
        total_aligned += d.get("aligned", 0)
    if total_w < min_total:
        return None
    return round(total_aligned / total_w * 100, 1)


def generate_site_data(legislators: dict, law_groups: dict):
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Legislators index
    SKIP_PATTERNS = ("NO INCORPORADO", "PENDIENTE DE INCORPORACION", "A DESIGNAR")
    leg_index = []
    for key, leg in sorted(legislators.items(), key=lambda x: x[0]):
        name_upper = key.upper()
        if any(p in name_upper for p in SKIP_PATTERNS) or key.strip(". ") == "":
            continue

        # Compute terms early so we can derive per-coalition alignment sums
        terms = compute_terms(leg)
        leg["_terms"] = terms  # stash for reuse in detail file output

        alignment_pj  = compute_weighted_alignment(leg["yearly_alignment"], "PJ")
        alignment_pro = compute_weighted_alignment(leg["yearly_alignment"], "PRO")
        alignment_lla = compute_weighted_alignment(leg["yearly_alignment"], "LLA")

        # Sum aligned vote counts per coalition (applying same year masks as
        # compute_weighted_alignment so coalition values are null when the
        # legislator didn't serve during that coalition's era).
        def _sum_aligned(coalition, min_total=5):
            total_w = 0
            total_aligned = 0
            for yr_str, data in leg["yearly_alignment"].items():
                try:
                    yint = int(yr_str)
                except (ValueError, TypeError):
                    continue
                d = data.get(coalition, {})
                tot = d.get("total", 0)
                if tot < min_total:
                    continue
                if coalition == "UCR" and yint > 2014:
                    continue
                if coalition in ("JxC", "PRO") and not (2015 <= yint <= 2023):
                    continue
                if coalition == "LLA" and yint < 2024:
                    continue
                total_w += tot
                total_aligned += d.get("aligned", 0)
            return total_aligned if total_w > 0 else None

        votes_pj  = _sum_aligned("PJ")
        votes_ucr = _sum_aligned("UCR")
        votes_pro = _sum_aligned("PRO")
        votes_lla = _sum_aligned("LLA")

        total_votes = sum(
            s.get("total", 0) for s in leg["yearly_stats"].values()
        )

        # Compute presentismo, ausencias, abstenciones for ranking.
        # Exclude trailing AUSENTE votes after the legislator's last
        # active (non-AUSENTE) vote — these occur when a legislator
        # leaves office (death, resignation, new post) but remains in
        # the chamber roster until the seat is formally vacated.
        trailing_ausente = _count_trailing_ausente(leg["votes"])

        total_ausente = sum(
            s.get("AUSENTE", 0) for s in leg["yearly_stats"].values()
        )
        total_abstencion = sum(
            s.get("ABSTENCION", 0) for s in leg["yearly_stats"].values()
        )
        effective_total = total_votes - trailing_ausente
        effective_ausente = total_ausente - trailing_ausente
        total_present = effective_total - effective_ausente
        presentismo_pct = round(total_present / effective_total * 100, 1) if effective_total > 0 else None

        chambers = sorted(set(leg["chambers"]))
        chamber_display = (
            "+".join(chambers) if len(chambers) > 1
            else chambers[0] if chambers
            else leg["chamber"]
        )

        # Per-coalition alignment (restricted to years within terms of each coalition)
        by_co = compute_per_coalition_alignment(
            terms, leg["yearly_alignment"], leg["yearly_stats"]
        )

        # Coalition from current bloc (reflects current affiliation).
        # Use the legislator's actual current bloc rather than the dominant
        # bloc of the latest term, since a legislator may have switched blocs
        # mid-term (e.g. from LLA to Provincias Unidas).
        if terms:
            latest_yr = max(t["yt"] for t in terms)
            cur_bloc_co = _classify_bloc_for_term(
                _normalize_bloc_display(leg["bloc"]), latest_yr
            )
            coalition_display = _era_coalition(cur_bloc_co, latest_yr)
        else:
            coalition_display = leg["coalition"]

        display_name = _normalize_display_name(leg["name"])

        leg_index.append({
            "k": key,
            "n": display_name,
            "c": chamber_display,
            "b": _normalize_bloc_display(leg["bloc"]),
            "p": leg["province"],
            "co": coalition_display,
            "apj": alignment_pj,
            "apro": alignment_pro,
            "alla": alignment_lla,
            "vpj": votes_pj,
            "vucr": votes_ucr,
            "vpro": votes_pro,
            "vlla": votes_lla,
            "tv": total_votes,
            "ph": leg.get("photo", ""),
            "pres": presentismo_pct,
            "aus": total_ausente,
            "abst": total_abstencion,
            "by_co": by_co,
        })

    save_json(DOCS_DATA_DIR / "legislators.json", leg_index)
    log.info(f"Generated legislators index with {len(leg_index)} entries")

    # 2. Individual legislator detail files
    leg_details_dir = DOCS_DATA_DIR / "legislators"
    leg_details_dir.mkdir(parents=True, exist_ok=True)

    total_legs = len(legislators)
    count = 0
    start_time = time.time()

    for key, leg in legislators.items():
        yearly_alignment_pct = {}
        for yr, data in sorted(leg["yearly_alignment"].items()):
            yearly_alignment_pct[yr] = {}
            try:
                yint = int(yr)
            except Exception:
                yint = None
            for coalition in ["PJ", "UCR", "JxC", "PRO", "LLA"]:
                total = data.get(coalition, {}).get("total", 0)
                aligned = data.get(coalition, {}).get("aligned", 0)
                pct = None
                # Apply year masks for opposition coalitions
                if coalition == "UCR":
                    if yint is not None and yint <= 2014:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                elif coalition in ("JxC", "PRO"):
                    if yint is not None and 2015 <= yint <= 2023:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                elif coalition == "LLA":
                    if yint is not None and yint >= 2024:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                else:
                    # PJ: always compute when enough votes
                    pct = round(aligned / total * 100, 1) if total > 5 else None

                yearly_alignment_pct[yr][coalition] = pct

        # Build waffle groups — merge by common_name so that e.g. all
        # "Ley Bases" O.D. numbers/dates become a single law entry
        waffle_groups = defaultdict(
            lambda: {"name": "", "votes": [], "year": None,
                     "common_name": None}
        )
        for vote in leg["votes"]:
            ln = vote.get("ln", "")
            # Determine merge key: use common_name if available, else gk.
            # Include the year so that recurring laws (Presupuesto, Consenso
            # Fiscal, etc.) produce one waffle row per year instead of a single
            # row merging all years together.
            # Use the pre-computed 'cn' field first (avoids re-deriving via
            # keyword matching, which fails for short names like "Presupuesto"
            # that don't self-match their own keywords).
            common_name = vote.get("cn") or (get_common_name(ln) if ln else None)
            if common_name:
                yr = vote.get("yr", "")
                merge_key = f"COMMON|{common_name}|{yr}" if yr else f"COMMON|{common_name}"
            else:
                gk = vote.get("gk", "")
                merge_key = gk if gk else f"SINGLE_{vote['vid']}"

            wg = waffle_groups[merge_key]
            if not wg["name"]:
                wg["name"] = ln or vote.get("t", "")
            if common_name:
                wg["common_name"] = common_name
                wg["name"] = common_name

            # Mark whether this is an "En General" vote
            al = vote.get("al", "")
            is_general = (al == "En General"
                          or "EN GENERAL" in vote.get("t", "").upper()
                          or "VOT. EN GRAL" in vote.get("t", "").upper())

            entry = {
                "v": vote["v"],
                "al": al,
                "t": vote.get("t", ""),
                "vid": vote.get("vid"),
                "ch": vote.get("ch"),
                "g": is_general,
            }
            if vote.get("url"):
                entry["url"] = vote["url"]
            wg["votes"].append(entry)
            if vote.get("yr") and not wg["year"]:
                wg["year"] = vote["yr"]

        waffle_list = []
        for gk, wg in waffle_groups.items():
            # Ensure at least one vote is marked g:True so the waffle always
            # has a prominent "summary" tile.  If only one votación exists,
            # promote it to "En General".  For multi-vote groups without an
            # EN GENERAL companion, leave as-is (no fake AUSENTE).
            if not any(v["g"] for v in wg["votes"]):
                if len(wg["votes"]) == 1:
                    # Single votación without En General label: promote it
                    wg["votes"][0]["g"] = True

            # pick first available vote URL to act as law link
            law_url = ""
            for vote in wg["votes"]:
                if vote.get("url"):
                    law_url = vote["url"]
                    break

            waffle_list.append({
                "gk": gk,
                "name": wg["name"][:120],
                "year": wg["year"],
                "url": law_url,
                "votes": wg["votes"],
                "notable": wg.get("common_name") is not None,
            })
        waffle_list.sort(key=lambda x: (-(x["year"] or 0), x["name"]))

        leg_terms = leg.get("_terms") or compute_terms(leg)
        if leg_terms:
            detail_coalition = leg_terms[-1]["co"]
        else:
            detail_coalition = leg["coalition"]

        display_name = _normalize_display_name(leg["name"])

        detail = {
            "name": display_name,
            "name_key": key,
            "photo": leg.get("photo", ""),
            "chambers": sorted(set(leg["chambers"])),
            "chamber": leg["chamber"],
            "bloc": _normalize_bloc_display(leg["bloc"]),
            "province": leg["province"],
            "coalition": detail_coalition,
            "yearly_stats": leg["yearly_stats"],
            "trailing_ausente": _count_trailing_ausente(leg["votes"]),
            "yearly_alignment": yearly_alignment_pct,
            "alignment": {
                c: compute_weighted_alignment(leg["yearly_alignment"], c)
                for c in ["PJ", "UCR", "PRO", "JxC", "LLA"]
            },
            "era_alignment": {
                "1993-2014": {
                    "PJ":  compute_era_alignment(leg["yearly_alignment"], "PJ",  1993, 2014),
                    "UCR": compute_era_alignment(leg["yearly_alignment"], "UCR", 1993, 2014),
                },
                "2015-2023": {
                    "PJ":  compute_era_alignment(leg["yearly_alignment"], "PJ",  2015, 2023),
                    "PRO": compute_era_alignment(leg["yearly_alignment"], "PRO", 2015, 2023),
                },
                "2024-2026": {
                    "PJ":  compute_era_alignment(leg["yearly_alignment"], "PJ",  2024, 2026),
                    "LLA": compute_era_alignment(leg["yearly_alignment"], "LLA", 2024, 2026),
                },
            },
            "terms": leg.get("_terms") or compute_terms(leg),
            "votes": leg["votes"],
            "laws": waffle_list,
        }

        safe_name = re.sub(r"[^A-Z0-9_]", "_", key)[:80]
        # time the JSON write to detect slow IO
        write_start = time.time()
        save_json(leg_details_dir / f"{safe_name}.json", detail)
        write_elapsed = time.time() - write_start
        count += 1
        # log progress periodically to help diagnose stalls
        if count % 100 == 0 or count == total_legs:
            total_elapsed = time.time() - start_time
            log.info(
                f"Wrote {count}/{total_legs} legislator files; last_write={write_elapsed:.2f}s; total_elapsed={total_elapsed:.2f}s"
            )

    log.info(f"Generated {len(legislators)} legislator detail files")

    # 3. Votaciones summary
    votaciones_summary = {"diputados": [], "senadores": []}

    for chamber in ["diputados", "senadores"]:
        votaciones = load_all_votaciones_from_db(chamber)
        for v in votaciones:
            votaciones_summary[chamber].append({
                "id": v.get("id"),
                "title": v.get("title", "")[:200],
                "date": clean_date(v.get("date", "")),
                "result": v.get("result", ""),
                "type": v.get("type", ""),
                "afirmativo": v.get("afirmativo", 0),
                "negativo": v.get("negativo", 0),
                "abstencion": v.get("abstencion", 0),
                "ausente": v.get("ausente", 0),
            })

    save_json(DOCS_DATA_DIR / "votaciones.json", votaciones_summary)
    log.info("Generated votaciones summary")

    # 3b. Law detail data (per-coalition vote breakdowns for law search)
    laws_detail, votes_by_year = build_law_detail_data(law_groups)
    save_json(DOCS_DATA_DIR / "laws_detail.json", laws_detail)
    log.info(f"Generated laws_detail.json with {len(laws_detail)} law entries")

    # 3c. Per-year voter-names indices (loaded on-demand on first bar-click)
    votes_dir = DOCS_DATA_DIR / "votes"
    votes_dir.mkdir(parents=True, exist_ok=True)
    total_votaciones = 0
    for year, ydata in sorted(votes_by_year.items()):
        save_json(votes_dir / f"votes_{year}.json", ydata)
        total_votaciones += len(ydata["v"])
    log.info(f"Generated {len(votes_by_year)} per-year vote files "
             f"({total_votaciones} votaciones total)")

    # 4. Law names list
    law_names_set = set()
    for g in law_groups.values():
        cn = g.get("common_name")
        if cn:
            law_names_set.add(cn)
        else:
            t = g.get("title", "").strip()
            if t and len(t) > 5:
                law_names_set.add(t[:120])
    save_json(DOCS_DATA_DIR / "law_names.json", sorted(law_names_set))
    log.info(f"Generated {len(law_names_set)} unique law names")

    # 5. Global stats  (use leg_index count to exclude placeholder entries)
    stats = {
        "last_updated": datetime.now().isoformat(),
        "total_legislators": len(leg_index),
        "total_diputados": sum(
            1 for e in leg_index if "diputados" in (e.get("c") or "")
        ),
        "total_senadores": sum(
            1 for e in leg_index if "senadores" in (e.get("c") or "")
        ),
        "total_votaciones_diputados": len(votaciones_summary["diputados"]),
        "total_votaciones_senadores": len(votaciones_summary["senadores"]),
        "years_covered": sorted(set(
            yr for leg in legislators.values()
            for yr in leg["yearly_stats"].keys()
        )),
        "years_diputados": list(practical_year_range(sorted(set(
            str(extract_year(v["date"]))
            for v in votaciones_summary["diputados"]
            if v.get("date") and extract_year(v["date"])
        )))),
        "years_senadores": list(practical_year_range(sorted(set(
            str(extract_year(v["date"]))
            for v in votaciones_summary["senadores"]
            if v.get("date") and extract_year(v["date"])
        )))),
        "total_laws": len(law_groups),
    }
    save_json(DOCS_DATA_DIR / "stats.json", stats)
    log.info("Generated global stats")


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix('.tmp')
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=None,
                      separators=(",", ":"))
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                # fsync may not be available on all platforms; ignore if it fails
                pass
        # Atomic replace to avoid truncated files if process is interrupted
        os.replace(tmp_path, path)
    except Exception as e:
        log.exception(f"Failed to write JSON to {path}: {e}")
        # Attempt best-effort write directly
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=None,
                          separators=(",", ":"))
        except Exception:
            log.exception(f"Fallback write also failed for {path}")


def main():
    log.info("Como Voto - Data Processor")
    log.info(f"Loading votaciones from {DATA_DIR}")

    # Load from consolidated DBs
    all_votaciones = []
    all_votaciones.extend(load_all_votaciones_from_db("diputados"))
    all_votaciones.extend(load_all_votaciones_from_db("senadores"))

    if not all_votaciones:
        log.warning("No votaciones found. Run scraper.py first.")
        generate_site_data({}, {})
        return

    log.info(f"Loaded {len(all_votaciones)} votaciones total")

    # Sort chronologically so that the last-seen bloc per legislator
    # reflects their most recent political affiliation.
    def _votacion_sort_key(v: dict) -> str:
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", v.get("date", ""))
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return "0000-00-00"

    all_votaciones.sort(key=_votacion_sort_key)
    log.info("Sorted votaciones chronologically")

    law_groups = build_law_groups(all_votaciones)
    log.info(f"Identified {len(law_groups)} law groups")

    photo_map = load_photo_maps()
    log.info(f"Loaded photo map: {len(photo_map)} entries")

    legislators = build_legislator_data(all_votaciones, law_groups)
    log.info(f"Found {len(legislators)} unique legislators")

    attach_photos(legislators, photo_map)

    generate_site_data(legislators, law_groups)

    log.info("Processing complete!")


if __name__ == "__main__":
    main()

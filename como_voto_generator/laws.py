from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict

from .normalization import extract_section_label

# ---------------------------------------------------------------------------
# Common law names mapping
# ---------------------------------------------------------------------------
COMMON_LAW_NAMES = [
    # --- Major 2023-2024+ laws ---
    (["bases y puntos de partida", "ley de bases", "ley bases"], "Ley Bases"),
    (["medidas fiscales paliativas", "paquete fiscal"], "Paquete Fiscal"),
    (
        [
            "régimen de incentivo para grandes inversiones",
            "regimen de incentivo para grandes inversiones",
            "rigi",
        ],
        "RIGI",
    ),
    (["decreto de necesidad y urgencia 70", "dnu 70"], "DNU 70/2023"),

    # --- Economy & taxes ---
    (["impuesto a las ganancias"], "Impuesto a las Ganancias"),
    (["bienes personales"], "Bienes Personales"),
    # Specific glacier rules before the generic "ley de presupuesto" rule so
    # titles like "PRESUPUESTO MINIMOS PARA LA PROTECCION DE LOS GLACIARES" are
    # correctly grouped under Ley de Glaciares rather than Presupuesto.
    (
        [
            "presupuesto minimos para la proteccion de los glaciares",
            "presupuesto mínimos para la protección de los glaciares",
            "presupuestos minimos para la proteccion de los glaciares",
            "presupuestos mínimos para la protección de los glaciares",
        ],
        "Ley de Glaciares",
    ),
    (
        [
            "presupuesto general",
            "presupuesto de la administración",
            "presupuesto de la administracion",
            "ley de presupuesto",
        ],
        "Presupuesto",
    ),
    (["movilidad jubilatoria", "movilidad previsional"], "Movilidad Jubilatoria"),
    (["régimen previsional", "regimen previsional"], "Regimen Previsional"),
    (["privatización", "privatizacion"], "Privatizaciones"),
    (["deuda externa", "reestructuración de deuda", "reestructuracion de deuda"], "Deuda Externa"),
    (
        ["monotributo", "régimen simplificado para pequeños contribuyentes", "regimen simplificado para pequeños contribuyentes"],
        "Monotributo",
    ),
    (["consenso fiscal"], "Consenso Fiscal"),
    (["fondo monetario internacional", "fondo monetario"], "FMI"),
    (["derechos de exportación", "derechos de exportacion", "retenciones agropecuarias"], "Retenciones / Derechos de Exportacion"),

    # --- Electoral & institutional ---
    (["boleta única", "boleta unica"], "Boleta Unica de Papel"),
    (["ficha limpia"], "Ficha Limpia"),
    (["régimen electoral", "regimen electoral", "código electoral", "codigo electoral"], "Regimen Electoral"),
    (["paridad de género", "paridad de genero"], "Paridad de Genero"),
    (["consejo de la magistratura"], "Consejo de la Magistratura"),

    # --- Codes ---
    (["código procesal penal", "codigo procesal penal"], "Codigo Procesal Penal"),
    (["código penal", "codigo penal"], "Codigo Penal"),
    (["código civil", "codigo civil"], "Codigo Civil"),
    (["código aduanero", "codigo aduanero"], "Codigo Aduanero"),

    # --- Justice & security ---
    (["juicio en ausencia"], "Juicio en Ausencia"),
    (["régimen penal juvenil", "penal juvenil"], "Regimen Penal Juvenil"),
    (["lavado de activos"], "Lavado de Activos"),
    (["extinción de dominio", "extincion de dominio"], "Extincion de Dominio"),
    (["inteligencia nacional", "agencia federal de inteligencia"], "Inteligencia Nacional"),
    (["narcotráfico", "narcotrafico"], "Narcotráfico"),

    # --- Labor ---
    (["reforma laboral", "modernización laboral", "modernizacion laboral"], "Reforma Laboral"),
    (["teletrabajo"], "Teletrabajo"),
    (["trabajo agrario"], "Trabajo Agrario"),

    # --- Housing & property ---
    (["ley de alquileres", "locaciones urbanas"], "Ley de Alquileres"),
    (["tierras rurales", "dominio nacional sobre la propiedad"], "Tierras Rurales"),

    # --- Social & rights ---
    (
        ["interrupción voluntaria del embarazo", "interrupcion voluntaria del embarazo", "aborto"],
        "IVE / Aborto",
    ),
    (["violencia de género", "violencia de genero"], "Violencia de Género"),
    (["emergencia alimentaria"], "Emergencia Alimentaria"),
    (
        [
            "matrimonio igualitario",
            "matrimonio entre personas del mismo sexo",
            "matrimonio civil",
            "código civil, sobre matrimonio",
            "codigo civil, sobre matrimonio",
        ],
        "Matrimonio Igualitario",
    ),
    (
        [
            "identidad de género",
            "identidad de genero",
            "ley de identidad",
            "cd-76/11",
        ],
        "Ley de Identidad de Género",
    ),
    (
        [
            "expropiación del 51% de las acciones de ypf",
            "expropiacion del 51% de las acciones de ypf",
            "expropiación de ypf",
            "expropiacion de ypf",
            "ypf yacimientos petrolíferos federales",
            "ypf yacimientos petroliferos federales",
            "ley de ypf",
            "expropiación de yacimientos petrolíferos",
            "expropiacion de yacimientos petroliferos",
            "se declara de utilidad pública y sujeto a expropiación el 51%",
            "se declara de utilidad publica y sujeto a expropiacion el 51%",
            "expropiación el 51% del patrimonio",
            "expropiacion el 51% del patrimonio",
        ],
        "Expropiación del 51% de YPF",
    ),
    (
        [
            "cupo laboral trans",
            "cupo laboral travesti",
            "acceso al empleo formal para personas travestis",
            "acceso al empleo formal para pers travestis",
            "travesti, transexual",
            "travestis, transexuales",
        ],
        "Cupo Laboral Trans",
    ),
    (["salud mental"], "Salud Mental"),
    (["barrios populares"], "Barrios Populares"),

    # --- Education & science ---
    (['financiamiento universitario'], "Ley de Financiamiento Universitario"),
    (['educación sexual', "educacion sexual"], "Educacion Sexual"),
    (
        [
            "emergencia en discapacidad",
            "emergencia nacional en discapacidad",
        ],
        "Emergencia Nacional en Discapacidad",
    ),
    (
        [
            "insistencia proyecto de ley 27.793",
            "insistencia en la ley 27.793",
            "ley 27.793",
            "ley 27 793",
            "rechazo al decreto 681/25 del poder ejecutivo nacional por el cual se suspende la ejecucion de la insistida ley 27.793",
            "rechazo al decreto 681/25",
        ],
        "Emergencia Nacional en Discapacidad - rechazo del veto",
    ),
    (["insistencia proyecto de ley 27.795"], "Ley de Financiamiento Universitario - rechazo del veto"),
    (["insistencia proyecto de ley 27.796"], "Ley de Financiamiento Universitario - rechazo del veto"),

    # Variants for the university financing law (including senate titles)
    (
        [
            "financiamiento de la educación universitaria",
            "financiamiento de la educacion universitaria",
            "financiamiento de la educación universitaria y recomposición del salario docente",
            "financiamiento de la educacion universitaria y recomposicion del salario docente",
            "financiamiento universidades",
            "financiamiento universitario",
            "financiamiento de universidades nacionales",
            "financiamiento universidades nacionales",
            "ley de financiamiento de universidades nacionales",
            "ley de financiamiento universidades nacionales",
            "ley de financiamiento de universidades",
        ],
        "Ley de Financiamiento Universitario",
    ),

    # Veto / insistencia related entries for the same subject. Map these
    # to the requested veto canonical name.
    (
        [
            "insistencia en la sancion original del proyecto de ley registrado bajo el numero 27.795",
            "insistencia en la sancion original del proyecto de ley de financiamiento",
            "insistencia ante el veto presidencial financiamiento",
            "rechazo al veto financiamiento",
            "rechazo del veto financiamiento",
            "rechazo veto financiamiento",
            "veto presidencial financiamiento",
            "financiamiento de la educación universitaria",
            "financiamiento de la educacion universitaria",
            "financiamiento universitario",
            "financiamiento de universidades nacionales",
        ],
        "Ley de Financiamiento Universitario - rechazo del veto",
    ),

    # Specific science/technology laws (must come before general "Financiamiento Cientifico")
    (
        [
            "emergencia y financiamiento del sistema nacional de ciencia, tecnología e innovación",
            "emergencia y financiamiento del sistema nacional de ciencia, tecnologia e innovacion",
            "emergencia y financiamiento del sistema nacional de ciencia",
        ],
        "Emergencia y Financiamiento Científico",
    ),
    (
        [
            "plan nacional de ciencia, tecnología e innovación 2030",
            "plan nacional de ciencia, tecnologia e innovacion 2030",
            "plan nacional de ciencia 2030",
        ],
        "Plan Nacional de Ciencia",
    ),
    (
        [
            "ley de financiamiento del sist. nacional de ciencia, tecnología e innovación",
            "ley de financiamiento del sist. nacional de ciencia, tecnologia e innovacion",
            "ley de financiamiento del sistema nacional de ciencia",
            "ley de financiamiento del sist. nacional de ciencia",
        ],
        "Ley de Financiamiento Científico",
    ),
    (
        [
            "financiamiento de la ciencia",
            "financiamiento científico",
            "financiamiento cientifico",
            "ciencia, tecnología e innovación",
            "ciencia, tecnologia e innovacion",
            "ciencia y tecnología",
            "ciencia y tecnologia",
        ],
        "Financiamiento Cientifico",
    ),

    # --- Health ---
    (["cannabis medicinal", "uso medicinal de la planta de cannabis"], "Cannabis Medicinal"),
    (
        [
            "cadena de frío de los medicamentos",
            "cadena de frio de los medicamentos",
            "producción pública de medicamentos",
            "produccion publica de medicamentos",
        ],
        "Ley de Medicamentos",
    ),

    # --- Environment ---
    (["etiquetado frontal"], "Etiquetado Frontal"),
    (["humedales"], "Ley de Humedales"),
    (["manejo del fuego"], "Manejo del Fuego"),
    (
        [
            "glaciares",
            "presupuesto minimos para la proteccion de los glaciares",
            "presupuesto mínimos para la protección de los glaciares",
            "regimen de presupuestos minimos para la preservacion de los glaciares",
            "régimen de presupuestos mínimos para la preservación de los glaciares",
        ],
        "Ley de Glaciares",
    ),
    (
        [
            "energías renovables",
            "energias renovables",
            "fuentes renovables de energía",
            "fuentes renovables de energia",
            "energía renovable",
            "energia renovable",
        ],
        "Energias Renovables",
    ),

    # --- Consumer & commerce ---
    (["góndolas", "gondolas"], "Ley de Gondolas"),
    (["economía del conocimiento", "economia del conocimiento"], "Economia del Conocimiento"),
    (["compre argentino", "compre nacional"], "Compre Argentino"),

    # --- Media & communication ---
    (["servicios de comunicación audiovisual", "servicios de comunicacion audiovisual", "ley de medios"], "Ley de Medios"),

    # --- Transparency ---
    (["acceso a la información pública", "acceso a la informacion publica"], "Acceso a Info. Publica"),

    # --- Transport & safety ---
    (["seguridad vial", "tránsito y seguridad vial", "transito y seguridad vial"], "Seguridad Vial"),
    (["ludopatía", "ludopatia", "apuestas en línea", "apuestas en linea", "juegos de azar y apuestas"], "Ludopatia / Apuestas Online"),

    # --- Other ---
    (["defensa nacional"], "Defensa Nacional"),
    (["inocencia fiscal"], "Inocencia Fiscal"),
]

# ---------------------------------------------------------------------------
# Vote IDs to exclude from output (e.g. duplicate/procedural votes where a
# second vote on the same text is the definitive one).
# Format: "<chamber>:<id>" where chamber is "senadores" or "diputados".
# ---------------------------------------------------------------------------
EXCLUDED_VOTE_IDS: set[str] = {
    # Ley de Glaciares 29/09/2010: the Senate first voted NEGATIVO on its own
    # text, then AFIRMATIVO on the Diputados text (which became Ley 26.639).
    # Only keep the passing vote.
    "senadores:1072",
}


def COMMON_NORM(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )


# Precompute normalized keywords per rule so we don't re-normalize on every call.
_COMMON_LAW_RULES: list[tuple[list[str], str]] = []
for _keywords, _common_name in COMMON_LAW_NAMES:
    _COMMON_LAW_RULES.append(([COMMON_NORM(keyword) for keyword in _keywords], _common_name))

# ---------------------------------------------------------------------------
# AI names cache (lazy-loaded from data/ai_law_names.json)
# ---------------------------------------------------------------------------

_ai_names_cache: dict[str, str] | None = None


def _get_ai_names_cache() -> dict[str, str]:
    """Return the AI names cache, loading it from disk on first access."""
    global _ai_names_cache
    if _ai_names_cache is None:
        try:
            from .common import DATA_DIR
            cache_path = DATA_DIR / "ai_law_names.json"
            if cache_path.exists():
                with open(cache_path, encoding="utf-8") as f:
                    _ai_names_cache = json.load(f)
            else:
                _ai_names_cache = {}
        except Exception:
            _ai_names_cache = {}
    return _ai_names_cache


def _kw_matches(kw_norm: str, t_norm: str) -> bool:
    """Devuelve True si *kw_norm* se encuentra dentro de *t_norm*."""
    if len(kw_norm) <= 4:
        return bool(re.search(r"\b" + re.escape(kw_norm) + r"\b", t_norm))
    return kw_norm in t_norm


def get_common_name(title: str) -> str | None:
    """Devuelve el nombre común de ley que mejor coincide con *title* o None.

    Checks in order:
    1. Hardcoded COMMON_LAW_NAMES rules (keyword matching)
    2. AI-generated names cache (data/ai_law_names.json)
    """
    if not title:
        return None
    normalized_title = COMMON_NORM(title)

    # Prioritize veto/insistencia matches for the financiamiento law: if the
    # title mentions both a veto/insistencia and financiamiento, return the
    # specific veto canonical name so these votes are grouped separately.
    if "financiamiento" in normalized_title:
        veto_indicators = [
            "veto presidencial",
            "rechazo del veto",
            "rechazo al veto",
            "rechazo veto",
            "insistencia proyecto",
            "insistencia en la sancion",
            "insistencia en la sanción",
        ]
        if any(ind in normalized_title for ind in veto_indicators):
            return "Ley de Financiamiento Universitario - rechazo del veto"

    best_name: str | None = None
    best_score: tuple[int, int] = (0, 0)

    for norm_keywords, common_name in _COMMON_LAW_RULES:
        matched_length = 0
        matched_count = 0
        for keyword in norm_keywords:
            if _kw_matches(keyword, normalized_title):
                matched_length += len(keyword)
                matched_count += 1

        if matched_count > 0:
            score = (matched_length, matched_count)
            if score > best_score:
                best_score = score
                best_name = common_name

    if best_name is not None:
        return best_name

    # Fall back to AI-generated cache
    return _get_ai_names_cache().get(normalized_title)


# ---------------------------------------------------------------------------
# Law grouping
# ---------------------------------------------------------------------------

def extract_law_group_key(votacion: dict) -> str:
    """Extract a grouping key for a votacion.
    
    Priority:
    1. Use common_name (from law name recognition) + year for well-known laws
    2. Use O.D. number for laws with Orden del Día identifier
    3. Use Expediente number for laws with file number
    4. Use cleaned title as fallback
    """
    title = votacion.get("title", "")
    date = votacion.get("date", "")
    chamber = votacion.get("chamber", "")
    
    # Extract year for common_name grouping
    year = ""
    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", date)
    if date_match:
        year = date_match.group(1)[-2:]  # Last 2 digits of year
    
    # Check if this votacion has a recognized common_name
    common_name = votacion.get("_common_name")
    if common_name:
        # Group by common_name + chamber + year
        return f"{chamber}|COMMON:{common_name}|{year}"

    date_part = ""
    if date_match:
        date_part = date_match.group(1)

    od_match = re.search(r"(O\.?\s*D\.?\s*N?[°ºo]?\s*\d+(?:/\d+)?)", title, re.IGNORECASE)
    if od_match:
        od_num = re.sub(r"\s+", "", od_match.group(1).upper())
        return f"{chamber}|{od_num}|{date_part}"

    exp_match = re.search(r"(Exp(?:ediente)?\.?\s*N?[°ºo]?\s*[\d\-]+(?:/\d+)?)", title, re.IGNORECASE)
    if exp_match:
        exp_num = re.sub(r"\s+", "", exp_match.group(1).upper())
        return f"{chamber}|{exp_num}|{date_part}"

    cleaned = title.upper()
    cleaned = re.sub(r"\s*-?\s*EN\s+(GENERAL|PARTICULAR)\s*", " ", cleaned)
    cleaned = re.sub(r"\s*-?\s*ART[IÍ]?CULO?\s+\d+.*", "", cleaned)
    cleaned = re.sub(r"\s*-?\s*ART\.?\s+\d+.*", "", cleaned)
    cleaned = re.sub(r"\s*-?\s*MODIFICACIONES?\s+(AL|DEL)\s+SENADO.*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if len(cleaned) > 15:
        return f"{chamber}|{cleaned[:100]}|{date_part}"

    return f"{chamber}|SINGLE|{votacion.get('id', '')}"


def _title_section_priority(title: str, vtype: str = "") -> int:
    """Return a priority for using this title as the canonical group title.

    Lower number = more preferred.
    0 = no section label (best canonical title)
    1 = "En General"
    2 = "En Particular"
    3 = specific section (Capítulo, Título, Artículo) — least preferred
    """
    section = extract_section_label(title, vtype)
    if not section:
        return 0
    if section == "En General":
        return 1
    if section == "En Particular":
        return 2
    return 3


def _update_group_title(group: dict, title: str, vtype: str = "") -> None:
    """Update the group's canonical title, preferring section-free titles."""
    if not title:
        return
    current = group["title"]
    if not current:
        group["title"] = title
        return
    new_pri = _title_section_priority(title, vtype)
    cur_pri = _title_section_priority(current)
    if new_pri < cur_pri or (new_pri == cur_pri and len(title) > len(current)):
        group["title"] = title


def build_law_groups(all_votaciones: list[dict]) -> dict:
    groups = defaultdict(
        lambda: {
            "votaciones": [],
            "title": "",
            "date": "",
            "common_name": None,
            "chamber": "",
        }
    )

    # Pre-compute common_name for each votacion
    for votacion in all_votaciones:
        title = votacion.get("title", "")
        common_name = get_common_name(title)
        if not common_name:
            # Fall back to the known generic title for the 2024 Diputados veto vote.
            if (
                votacion.get("chamber") == "diputados"
                and votacion.get("id") == "5400"
                and COMMON_NORM(title) == "expte. 17-pe-2024."
            ):
                common_name = "Ley de Financiamiento Universitario - rechazo del veto"
        if common_name:
            votacion["_common_name"] = common_name

    for votacion in all_votaciones:
        key = extract_law_group_key(votacion)
        group = groups[key]
        group["votaciones"].append(votacion)
        _update_group_title(group, votacion.get("title", ""), votacion.get("type", ""))
        if not group["date"]:
            group["date"] = votacion.get("date", "")
        group["chamber"] = votacion.get("chamber", "")

    # For each group, determine which votacion is "En General"
    # If multiple have explicit En General designation, use the earliest by timestamp
    # If none has explicit En General, use the earliest by timestamp
    # IMPORTANT: Only mark as En General if there's no specific section (Título, Cap., Art.)
    from datetime import datetime
    
    def _parse_date(date_value: str) -> datetime:
        date_value = (date_value or "").strip()
        try:
            return datetime.strptime(date_value, "%d/%m/%Y - %H:%M")
        except (ValueError, AttributeError):
            try:
                return datetime.strptime(date_value[:10], "%d/%m/%Y")
            except (ValueError, AttributeError):
                return datetime.min
    
    for group in groups.values():
        votaciones = group["votaciones"]
        # Sort votaciones by parsed datetime so ordering is chronological
        votaciones.sort(key=lambda v: _parse_date(v.get("date", "")))
        
        # First, determine the section label for each votacion using the same logic as extract_section_label
        # Only consider it "En General" if extract_section_label returns "En General"
        explicit_en_general_indices = []
        for i, votacion in enumerate(votaciones):
            title = votacion.get("title", "")
            vtype = votacion.get("type", "")
            section_label = extract_section_label(title, vtype)
            if section_label == "En General":
                votacion["_is_en_general"] = True
                votacion["al"] = "En General"
                explicit_en_general_indices.append(i)
            else:
                votacion["_is_en_general"] = False
                if votacion.get("al") == "En General":
                    votacion["al"] = None
        
        # If there are explicit En General votaciones, mark only the earliest one
        if explicit_en_general_indices:
            earliest_idx = min(
                explicit_en_general_indices,
                key=lambda i: _parse_date(votaciones[i].get("date", ""))
            )
            # Unmark all others
            for i in explicit_en_general_indices:
                if i != earliest_idx:
                    votaciones[i]["_is_en_general"] = False
                    if votaciones[i].get("al") == "En General":
                        votaciones[i]["al"] = None
        elif len(votaciones) > 0:
            # No explicit En General, mark the earliest one overall
            earliest_idx = min(
                range(len(votaciones)),
                key=lambda i: _parse_date(votaciones[i].get("date", ""))
            )
            votaciones[earliest_idx]["_is_en_general"] = True
            votaciones[earliest_idx]["al"] = "En General"
            # Clear any other residual 'al' markers
            for i in range(len(votaciones)):
                if i != earliest_idx and votaciones[i].get("al") == "En General":
                    votaciones[i]["al"] = None

        common_name = next((v.get("_common_name") for v in votaciones if v.get("_common_name")), None)
        if not common_name:
            common_name = get_common_name(group["title"])
        if common_name:
            group["common_name"] = common_name

    return dict(groups)

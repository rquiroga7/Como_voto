from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime

from .common import DATA_DIR, DOCS_DATA_DIR, log, save_json
from .data_loading import clean_date, extract_year, load_all_votaciones_from_db, practical_year_range
from .laws import get_common_name
from .normalization import (
    NAME_ALIASES,
    classify_bloc_mapped,
    classify_bloc_party,
    extract_section_label,
    load_bloc_coalition_map,
    normalize_name,
    normalize_vote,
)

_PARTY_KEYS = ("pj", "ucr", "pro", "lla", "cc", "oth")


def build_law_detail_data(law_groups: dict) -> tuple[list[dict], dict[int, dict]]:
    """Construye el desglose de votos por ley y por partido para búsqueda de leyes."""
    laws: list[dict] = []
    all_vote_names: dict[int, dict[str, list[list[str]]]] = {}
    name_set: set[str] = set()
    votacion_counter = 0

    for group in law_groups.values():
        votaciones_raw = group.get("votaciones", [])
        if not votaciones_raw:
            continue

        display_name = group.get("common_name") or group.get("title", "")
        if not display_name or len(display_name.strip()) < 3:
            continue

        year: int | None = None
        chamber = group.get("chamber", "")
        for votacion in votaciones_raw:
            y = extract_year(votacion.get("date", ""))
            if y:
                year = y
                break
            if not chamber:
                chamber = votacion.get("chamber", "")

        vs_out: list[dict] = []
        for votacion in votaciones_raw:
            votes_list = votacion.get("votes", [])
            if not votes_list:
                continue

            # Tally votes per real party (not coalition)
            tallies: dict[str, list[int]] = {
                "pj": [0, 0, 0, 0],
                "ucr": [0, 0, 0, 0],
                "pro": [0, 0, 0, 0],
                "lla": [0, 0, 0, 0],
                "cc": [0, 0, 0, 0],
                "oth": [0, 0, 0, 0],
            }
            total = [0, 0, 0, 0]

            vote_idx = {
                "AFIRMATIVO": 0,
                "NEGATIVO": 1,
                "ABSTENCION": 2,
                "AUSENTE": 3,
            }

            names: dict[str, list[list[str]]] = {party_key: [[], [], [], []] for party_key in _PARTY_KEYS}

            for vote_row in votes_list:
                vote_str = normalize_vote(vote_row.get("vote", ""))
                idx = vote_idx.get(vote_str)
                if idx is None:
                    continue

                party = classify_bloc_party(vote_row.get("bloc", ""))
                party_key = party.lower() if party != "OTROS" else "oth"

                tallies[party_key][idx] += 1
                total[idx] += 1

                leg_name = vote_row.get("name", "").strip()
                if leg_name:
                    norm = normalize_name(leg_name)
                    norm = NAME_ALIASES.get(norm, norm)
                    names[party_key][idx].append(norm)
                    name_set.add(norm)

            if sum(total) == 0:
                continue

            vi = votacion_counter
            votacion_counter += 1
            all_vote_names[vi] = names

            title_str = votacion.get("title", "")
            vtype = votacion.get("type", "")
            # Use _is_en_general flag if available, otherwise extract from title
            if votacion.get("_is_en_general"):
                tp_label = "En General"
            else:
                tp_label = extract_section_label(title_str, vtype)

            entry: dict = {
                "t": title_str[:200],
                "tp": tp_label,
                "d": clean_date(votacion.get("date", "")),
                "r": votacion.get("result", ""),
                "vi": vi,
                "tot": total,
                "pj": tallies["pj"],
                "ucr": tallies["ucr"],
                "pro": tallies["pro"],
                "lla": tallies["lla"],
                "cc": tallies["cc"],
                "oth": tallies["oth"],
            }

            vid = votacion.get("id")
            if vid:
                entry["id"] = vid
            url = votacion.get("url", "")
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
        def _latest_vote_ts(law: dict) -> int:
            latest = datetime.min
            for vote_data in law.get("vs", []):
                vote_date = _parse_vote_date(vote_data.get("d", ""))
                if vote_date > latest:
                    latest = vote_date
            if latest == datetime.min:
                return 0
            return int(latest.timestamp())

        # Sort: notable (common_name) first, then by newest vote date desc, then by name.
        laws.sort(key=lambda x: (0 if x.get("cn") else 1, -_latest_vote_ts(x), x.get("n", "")))

    # Build per-year votes indices. Each year file gets its own compact name table.
    vi_to_year: dict[int, int] = {}
    for law in laws:
        year = law.get("y") or 0
        for vote_data in law.get("vs", []):
            vi = vote_data.get("vi")
            if vi is not None:
                vi_to_year[vi] = year

    year_vis: dict[int, list[int]] = defaultdict(list)
    for vi, year in vi_to_year.items():
        year_vis[year].append(vi)

    votes_by_year: dict[int, dict] = {}
    for year, vis in year_vis.items():
        year_name_set: set[str] = set()
        for vi in vis:
            party_names = all_vote_names.get(vi, {})
            for party_key in _PARTY_KEYS:
                for vote_i in range(4):
                    for name in party_names.get(party_key, [[], [], [], []])[vote_i]:
                        year_name_set.add(name)

        year_name_list = sorted(year_name_set)
        local_idx = {name: idx for idx, name in enumerate(year_name_list)}

        compact_votes: dict[str, dict] = {}
        for vi in vis:
            party_names = all_vote_names.get(vi, {})
            compact: dict[str, list[list[int]]] = {}
            for party_key in _PARTY_KEYS:
                arrays: list[list[int]] = [[], [], [], []]
                for vote_i in range(4):
                    for name in party_names.get(party_key, [[], [], [], []])[vote_i]:
                        arrays[vote_i].append(local_idx[name])
                if any(arrays[i] for i in range(4)):
                    compact[party_key] = arrays
            if compact:
                compact_votes[str(vi)] = compact

        votes_by_year[year] = {"n": year_name_list, "v": compact_votes}

    return laws, votes_by_year


def _parse_vote_date(date_value: str) -> datetime:
    """Parse vote dates in ``DD/MM/YYYY - HH:MM`` (or date-only) format."""
    date_value = (date_value or "").strip()
    try:
        return datetime.strptime(date_value, "%d/%m/%Y - %H:%M")
    except (ValueError, AttributeError):
        try:
            return datetime.strptime(date_value[:10], "%d/%m/%Y")
        except (ValueError, AttributeError):
            return datetime.min


def _count_trailing_ausente(
    votes: list[dict],
    terms: list[dict] | None = None,
) -> int:
    """Count AUSENTE votes that occur after the legislator's name no longer
    appears in votacion data.

    New logic: For each term (mandato), check if the legislator's name appears
    in votaciones through the end of their term. If their last vote (of any type)
    is an AUSENTE vote, it means they were still in office but absent - this
    should NOT count as trailing. Only count AUSENTE votes that occur after the
    legislator's name completely disappears from votacion data.

    The votes list contains all votes where the legislator's name appears
    (including AUSENTE). So if the last vote in the list is AUSENTE, the
    legislator was still in office - no trailing ausente.
    """
    if not votes:
        return 0

    from datetime import datetime

    def _parse_date(d: str) -> datetime:
        try:
            return datetime.strptime(d.split(" - ")[0], "%d/%m/%Y")
        except (ValueError, AttributeError):
            try:
                return datetime.strptime(d[:10], "%d/%m/%Y")
            except (ValueError, AttributeError):
                return datetime.min

    # Sort votes by date to find the last vote where the legislator's name appears
    sorted_votes = sorted(votes, key=lambda v: _parse_date(v.get("d", "")))
    if not sorted_votes:
        return 0

    # Get the last vote date where the legislator's name appears
    last_vote = sorted_votes[-1]
    last_present_date = _parse_date(last_vote.get("d", ""))
    last_vote_type = last_vote.get("v", "")

    # If the last vote is AUSENTE, the legislator was still in office
    # (their name was recorded). Don't count any trailing ausente.
    # This is the key change: AUSENTE means they were still in the roster.
    if last_vote_type == "AUSENTE":
        return 0

    # If the last vote is not AUSENTE, use the old logic as fallback:
    # count AUSENTE votes after the last non-AUSENTE vote
    non_ausente = [v for v in votes if v.get("v") != "AUSENTE"]
    if not non_ausente:
        return 0  # Never attended — don't exclude anything

    last_active_dt = max(_parse_date(v.get("d", "")) for v in non_ausente)
    trailing = sum(
        1 for v in votes
        if v.get("v") == "AUSENTE" and _parse_date(v.get("d", "")) > last_active_dt
    )
    return trailing


# ---------------------------------------------------------------------------
# Election data lookup for coalition classification
# ---------------------------------------------------------------------------
_ELECTION_INDEX: dict | None = None
_ELECTION_YEARS_SORTED: list[int] = []


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _normalize_display_name(name: str) -> str:
    """Normalize ``SURNAME, FIRSTNAME`` to a cleaner display style."""
    import re
    # Remove nicknames in quotes (e.g., "TOPO", "PIPI")
    name = re.sub(r'\s*"[^"]*"', '', name).strip()
    if "," not in name:
        return name
    surname, _, first = name.partition(",")
    first = first.strip()
    if not first:
        return name
    particles = {"de", "del", "la", "las", "los", "el", "y", "e"}
    words = first.split()
    result = []
    for index, word in enumerate(words):
        if word.lower() in particles and index > 0:
            result.append(word.lower())
        else:
            result.append(word.capitalize())
    return f"{surname.upper()}, {' '.join(result)}"


_BLOC_PARTICLES = {
    "de",
    "del",
    "la",
    "las",
    "los",
    "el",
    "y",
    "e",
    "por",
    "para",
    "en",
    "con",
    "sin",
    "al",
    "su",
}
_BLOC_ACRONYMS = {
    "PJ",
    "UCR",
    "PRO",
    "ARI",
    "GEN",
    "UNEN",
    "FIT",
    "PTS",
    "PO",
    "MST",
    "MID",
    "MODIN",
    "FREPASO",
    "FORJA",
    "UPT",
    "SI",
    "JSRN",
}
_ACCENT_MAP = {
    "union": "Unión",
    "civica": "Cívica",
    "civico": "Cívico",
    "produccion": "Producción",
    "producción": "Producción",
    "coalicion": "Coalición",
    "rio": "Río",
    "accion": "Acción",
    "concertacion": "Concertación",
    "integracion": "Integración",
    "renovacion": "Renovación",
    "innovacion": "Innovación",
    "evolucion": "Evolución",
    "democratico": "Democrático",
    "democrata": "Demócrata",
    "autonomia": "Autonomía",
    "educacion": "Educación",
    "inclusion": "Inclusión",
    "energia": "Energía",
    "republica": "República",
    "soberania": "Soberanía",
    "participacion": "Participación",
    "tucuman": "Tucumán",
    "cordoba": "Córdoba",
    "dialogo": "Diálogo",
}

# Party code to party name mapping
_PARTY_CODE_NAMES = {
    "PJ": "Partido Justicialista",
    "UCR": "Unión Cívica Radical",
    "LLA": "La Libertad Avanza",
    "CC-ARI": "Coalición Cívica ARI",
    "CC": "Coalición Cívica",
    "ARI": "Afirmación para una República Igualitaria",
    "FCC": "Frente Cívico de Córdoba",
    "AP": "Acción por la República",
    "MID": "Movimiento de Integración y Desarrollo",
    "PD": "Partido Demócrata",
    "PL": "Partido Liberal",
    "FE": "Fuerza Entrerriana",
    "UCeDé": "Unión del Centro Democrático",
    "UCyB": "Unión Celeste y Blanca",
    "CaG": "Cambio y Gloria",
    "Celeste": "Lista Celeste",
    "Cumplir": "Cumplir",
    "1RN": "Primero Río Negro",
    "PRFTU": "Partido Renovador Federal de Tucumán",
    "LTP": "Lealtad y Trabajo por la Provincia",
    "PLCo": "Partido Liberal de Corrientes",
    "ADN": "ADN",
    "3P": "Tercera Posición",
    "FL": "Fuerza Liberal",
    "UNITE": "Unite",
    "PD - VyF": "Partido Demócrata - Viento y Fuego",
    "Activar": "Activar",
    "PRO": "Propuesta Republicana",  # Party name (not coalition)
}

_UCR_SPLIT_KW = (
    "ucr",
    "radical",
    "coalición cívica",
    "coalicion civica",
    "evolución",
    "evolucion",
    "democracia para siempre",
)
_PJ_TERM_KW = (
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
)
_PRO_TERM_KW = (
    "pro ",
    "propuesta republicana",
    "cambiemos",
    "juntos por el cambio",
)
_LLA_TERM_KW = (
    "la libertad avanza",
    "libertad avanza",
)
_BLOC_ERA_OVERRIDES: dict[str, list[tuple[int, str]]] = {}


def _restore_accents(word: str) -> str:
    key = word.lower().rstrip(".,;:")
    suffix = word[len(key) :]
    if key in _ACCENT_MAP:
        replacement = _ACCENT_MAP[key]
        if word and word[0].isupper():
            return replacement + suffix
        return replacement[0].lower() + replacement[1:] + suffix
    return word


def _normalize_bloc_display(name: str) -> str:
    """Normalize bloc name capitalization/accenting for UI display."""
    if not name or not name.strip():
        return name

    name = name.replace(" -", " - ").replace("- ", " - ")
    while "  " in name:
        name = name.replace("  ", " ")

    segments = name.split(" - ")
    normalized_segments: list[str] = []
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        letters = [char for char in segment if char.isalpha()]
        if not letters:
            normalized_segments.append(segment)
            continue

        upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
        if upper_ratio > 0.6:
            words = []
            for word in segment.split():
                if "." in word and any(char.isalpha() for char in word):
                    words.append(word.upper())
                elif "-" in word:
                    parts = word.split("-")
                    words.append("-".join(part.capitalize() for part in parts))
                else:
                    words.append(word.capitalize())
            segment = " ".join(words)

        words = segment.split()
        for index, word in enumerate(words):
            if "-" in word and len(word) > 1:
                parts = word.split("-")
                for part_index, part in enumerate(parts):
                    stripped_part = part.strip("()[].,")
                    if stripped_part.upper() in _BLOC_ACRONYMS:
                        parts[part_index] = part.upper()
                    elif part and part[0].islower():
                        parts[part_index] = part.capitalize()
                    parts[part_index] = _restore_accents(parts[part_index])
                words[index] = "-".join(parts)
                continue

            stripped = word.strip("()[].,")
            if "." in stripped and any(char.isalpha() for char in stripped):
                words[index] = word.upper()
            elif stripped.upper() in _BLOC_ACRONYMS:
                words[index] = word.upper()
            elif index > 0 and stripped.lower() in _BLOC_PARTICLES and "." not in word:
                words[index] = word.lower()
            words[index] = _restore_accents(words[index])
        normalized_segments.append(" ".join(words))

    return " - ".join(normalized_segments)


def _era_coalition(base_coalition: str, term_start_year: int) -> str:
    """Map electoral coalition to display coalition based on era.

    - PJ: always PJ
    - UCR: UCR before 2015, JxC during 2015-2023 (as part of Juntos por el Cambio),
           OTROS from 2024+ (UCR ran separately, not part of major coalition)
    - JxC: JxC during 2015-2023 (Cambiemos/Juntos por el Cambio era)
    - PRO: OTROS (PRO was never a standalone major coalition; was part of JxC 2015-2023)
    - LLA: always LLA
    """
    if base_coalition == "PJ":
        return "PJ"
    if base_coalition == "UCR":
        if term_start_year < 2015:
            return "UCR"
        if term_start_year < 2024:
            return "JxC"  # UCR was part of Juntos por el Cambio
        return "OTROS"  # 2024+: UCR ran separately (not part of major coalition)
    if base_coalition == "JxC":
        if term_start_year < 2015:
            return "OTROS"  # JxC didn't exist before 2015
        if term_start_year < 2024:
            return "JxC"
        return "LLA"  # 2024+: most JxC members joined LLA
    if base_coalition == "PRO":
        return "OTROS"  # PRO was never a standalone major coalition
    if base_coalition == "LLA":
        return "LLA"
    return "OTROS"


def _get_party_name(party_code: str) -> str:
    """Get the full party name from a party code."""
    if not party_code:
        return ""
    return _PARTY_CODE_NAMES.get(party_code, party_code)


def _classify_bloc_for_term(bloc_name: str, year: int) -> str:
    """Classify bloc into PJ/UCR/PRO/LLA/OTROS for mandate-era assignment."""
    key = bloc_name.lower().strip()

    if key in _BLOC_ERA_OVERRIDES:
        for cutoff, coalition in sorted(_BLOC_ERA_OVERRIDES[key], reverse=True):
            if year >= cutoff:
                return coalition

    mapping = load_bloc_coalition_map()
    if key in mapping:
        coalition = mapping[key]
        if coalition == "PRO":
            if any(keyword in key for keyword in _UCR_SPLIT_KW):
                return "UCR"
            return "OTROS"  # PRO was never a standalone major coalition
        if coalition == "UCR":
            return "UCR"
        if coalition in ("PJ", "LLA"):
            return coalition
        return "OTROS"

    if any(keyword in key for keyword in _PJ_TERM_KW):
        return "PJ"
    if any(keyword in key for keyword in _UCR_SPLIT_KW):
        return "UCR"
    if any(keyword in key for keyword in _PRO_TERM_KW):
        return "OTROS"  # PRO was never a standalone major coalition
    if any(keyword in key for keyword in _LLA_TERM_KW):
        return "LLA"

    fallback = classify_bloc_mapped(bloc_name)
    if fallback == "PRO" and any(keyword in key for keyword in _UCR_SPLIT_KW):
        return "UCR"
    if fallback in ("PJ", "LLA"):
        return fallback
    return "OTROS"


def _norm_province(province: str) -> str:
    normalized = _strip_accents(province.strip()).upper()
    normalized = normalized.replace(".", "").replace(",", "")
    if normalized in ("CABA", "CAPITAL FEDERAL", "CIUDAD AUTONOMA DE BUENOS AIRES"):
        return "CAPITAL FEDERAL"
    return normalized


def _name_tokens(name: str) -> set[str]:
    normalized = _strip_accents(name).upper().replace(",", " ")
    tokens = set(normalized.split())
    for token in ("DE", "DEL", "LA", "LOS", "LAS", "Y", "E", "S", "J"):
        tokens.discard(token)
    return {token for token in tokens if len(token) > 1}


def _load_election_index() -> None:
    global _ELECTION_INDEX, _ELECTION_YEARS_SORTED
    if _ELECTION_INDEX is not None:
        return

    path = DATA_DIR / "election_legislators.json"
    if not path.exists():
        log.warning("election_legislators.json not found - run tools/scrape_elections.py")
        _ELECTION_INDEX = {}
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"Failed to load election_legislators.json: {exc}")
        _ELECTION_INDEX = {}
        return

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
                _ELECTION_INDEX.setdefault(key, []).append(
                    {
                        "tokens": tokens,
                        "coalition": entry["coalition"],
                        "name": entry["name"],
                        "party_code": entry.get("party_code"),
                        "alliance": entry.get("alliance", ""),
                        "suplente": entry.get("suplente", False),
                    }
                )

    _ELECTION_YEARS_SORTED = sorted(years)
    log.info(
        f"Loaded election index: {len(raw)} years, "
        f"{sum(len(values) for values in _ELECTION_INDEX.values())} candidates"
    )


def _find_election_year(term_start: int) -> int | None:
    _load_election_index()
    best = None
    for election_year in _ELECTION_YEARS_SORTED:
        if election_year <= term_start:
            best = election_year
    return best


def _match_legislator_to_election(
    name_key: str,
    province: str,
    chamber: str,
    election_year: int,
) -> dict | None:
    _load_election_index()
    if not _ELECTION_INDEX:
        return None

    key = (election_year, _norm_province(province), chamber)
    candidates = _ELECTION_INDEX.get(key, [])
    if not candidates:
        return None

    legislator_tokens = _name_tokens(name_key)
    if not legislator_tokens:
        return None

    best_score = 0.0
    best_match = None
    for candidate in candidates:
        candidate_tokens = candidate["tokens"]
        shared = legislator_tokens & candidate_tokens
        if not shared:
            continue
        score = len(shared) / min(len(legislator_tokens), len(candidate_tokens))
        is_better = score > best_score or (
            score == best_score
            and best_match
            and best_match.get("suplente")
            and not candidate.get("suplente")
        )
        if is_better:
            best_score = score
            best_match = candidate

    if best_score >= 0.6 and best_match:
        return {
            "coalition": best_match["coalition"],
            "party_code": best_match.get("party_code"),
            "alliance": best_match.get("alliance", ""),
        }
    return None


def compute_terms(leg: dict, min_votes: int = 5) -> list[dict]:
    """Derive term records from yearly bloc/province traces plus vote activity."""
    mandate_len = {"diputados": 4, "senadores": 6}

    yr_blocs = leg.get("_yr_blocs", {})
    yr_provinces = leg.get("_yr_provinces", {})
    yearly_stats = leg.get("yearly_stats", {})
    terms: list[dict] = []

    for chamber, year_dict in yr_blocs.items():
        max_len = mandate_len.get(chamber, 6)
        active = sorted(
            int(year_str)
            for year_str in year_dict
            if yearly_stats.get(year_str, {}).get("total", 0) >= min_votes
        )
        if not active:
            continue

        runs: list[list[int]] = []
        current = [active[0]]
        for year in active[1:]:
            if year - current[-1] <= 2:
                current.append(year)
            else:
                runs.append(current)
                current = [year]
        runs.append(current)

        for run in runs:
            index = 0
            while index < len(run):
                boundary = run[index] + max_len
                sub = [year for year in run[index:] if year <= boundary]
                index += len(sub)

                bloc_totals: dict[str, int] = {}
                for year in sub:
                    for bloc, count in year_dict.get(str(year), {}).items():
                        bloc_totals[bloc] = bloc_totals.get(bloc, 0) + count
                dominant_bloc = max(bloc_totals, key=bloc_totals.get) if bloc_totals else ""

                prov_totals: dict[str, int] = {}
                for year in sub:
                    for province, count in yr_provinces.get(chamber, {}).get(str(year), {}).items():
                        prov_totals[province] = prov_totals.get(province, 0) + count
                dominant_province = max(prov_totals, key=prov_totals.get) if prov_totals else leg.get("province", "")

                election_year = _find_election_year(min(sub))
                name_key = leg.get("name_key", "")
                electoral_coalition = None
                electoral_alliance = None
                electoral_party_code = None
                if election_year:
                    match = _match_legislator_to_election(name_key, dominant_province, chamber, election_year)
                    if match:
                        if match.get("coalition") and match["coalition"] != "OTROS":
                            electoral_coalition = match["coalition"]
                        elif match.get("party_code") and match["party_code"] in ("PJ", "UCR", "LLA"):
                            # Only use party_code as coalition for major parties
                            electoral_coalition = match["party_code"]
                        electoral_alliance = match.get("alliance", "")
                        electoral_party_code = match.get("party_code", "")
                if not electoral_coalition:
                    base = _classify_bloc_for_term(_normalize_bloc_display(dominant_bloc), max(sub))
                    electoral_coalition = _era_coalition(base, max(sub))

                # Use party name when available, otherwise alliance, otherwise dominant bloc
                if electoral_party_code:
                    display_alliance = _get_party_name(electoral_party_code)
                elif electoral_alliance:
                    display_alliance = electoral_alliance
                else:
                    display_alliance = _normalize_bloc_display(dominant_bloc)

                terms.append(
                    {
                        "ch": chamber,
                        "yf": min(sub),
                        "yt": max(sub),
                        "b": display_alliance,
                        "p": dominant_province,
                        "co_electoral": electoral_coalition,
                        "alliance": electoral_alliance if electoral_alliance else None,
                    }
                )

    terms.sort(key=lambda term: (term["yf"], term["ch"]))
    
    # Count election match statistics
    matched = sum(1 for t in terms if t.get("co_electoral"))
    unmatched = len(terms) - matched
    if unmatched > 0:
        log.info(f"  Terms without election match: {unmatched}/{len(terms)}")
    
    for term in terms:
        # Use co_electoral when available (from election match), otherwise fall back to bloc-based classification
        if term.get("co_electoral"):
            term["co"] = term["co_electoral"]
        else:
            base = _classify_bloc_for_term(term["b"], term["yt"])
            term["co"] = _era_coalition(base, term["yt"])
    return terms


def compute_per_coalition_alignment(
    terms: list[dict],
    yearly_alignment: dict,
    yearly_stats: dict,
    min_total: int = 5,
) -> dict[str, dict]:
    """Alignment vote sums restricted to years served under each coalition."""
    coalition_years: dict[str, set[int]] = {}
    coalition_bloc: dict[str, str] = {}
    coalition_yf_yt: dict[str, tuple[int, int]] = {}
    for term in terms:
        coalition = term.get("co_electoral") or term["co"]
        coalition_years.setdefault(coalition, set())
        for year in range(term["yf"], term["yt"] + 1):
            coalition_years[coalition].add(year)
        coalition_bloc[coalition] = term["b"]
        # Track min/max year for each coalition
        if coalition not in coalition_yf_yt:
            coalition_yf_yt[coalition] = (term["yf"], term["yt"])
        else:
            prev_yf, prev_yt = coalition_yf_yt[coalition]
            coalition_yf_yt[coalition] = (min(prev_yf, term["yf"]), max(prev_yt, term["yt"]))

    result: dict[str, dict] = {}
    for coalition, years in coalition_years.items():
        sums = {"vpj": 0, "vucr": 0, "vpro": 0, "vlla": 0, "tv": 0}
        has_any = False
        for year_str, data in yearly_alignment.items():
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                continue
            if year not in years:
                continue
            for label, field in [("PJ", "vpj"), ("UCR", "vucr"), ("PRO", "vpro"), ("LLA", "vlla")]:
                aligned_data = data.get(label, {})
                total = aligned_data.get("total", 0)
                if total < min_total:
                    continue
                if label == "UCR" and year > 2014:
                    continue
                if label in ("JxC", "PRO") and not (2015 <= year <= 2023):
                    continue
                if label == "LLA" and year < 2024:
                    continue
                sums[field] += aligned_data.get("aligned", 0)
                has_any = True
        for year_str, stats in yearly_stats.items():
            try:
                year = int(year_str)
            except (ValueError, TypeError):
                continue
            if year in years:
                sums["tv"] += stats.get("total", 0)
        if has_any or sums["tv"] > 0:
            sums["b"] = _normalize_bloc_display(coalition_bloc.get(coalition, ""))
            yf, yt = coalition_yf_yt.get(coalition, (None, None))
            if yf is not None and yt is not None:
                sums["yf"] = yf
                sums["yt"] = yt
            result[coalition] = sums
    return result


def compute_weighted_alignment(yearly_alignment: dict, coalition: str, min_total: int = 5) -> float | None:
    """Devuelve el % de alineamiento total como media ponderada anual."""
    total_weight = 0
    total_aligned = 0
    for year_str, data in yearly_alignment.items():
        try:
            year = int(year_str)
        except (ValueError, TypeError):
            continue

        coalition_data = data.get(coalition, {})
        total = coalition_data.get("total", 0)
        if total < min_total:
            continue

        # Apply the same year masks used for per-year display
        if coalition == "UCR" and year > 2014:
            continue
        if coalition in ("JxC", "PRO") and not (2015 <= year <= 2023):
            continue
        if coalition == "LLA" and year < 2024:
            continue

        total_weight += total
        total_aligned += coalition_data.get("aligned", 0)

    if total_weight == 0:
        return None
    return round(total_aligned / total_weight * 100, 1)


def compute_era_alignment(
    yearly_alignment: dict,
    coalition: str,
    year_min: int,
    year_max: int,
    min_total: int = 5,
) -> float | None:
    """% de alineamiento ponderado para ``coalition`` en [year_min, year_max]."""
    total_weight = 0
    total_aligned = 0
    for year_str, data in yearly_alignment.items():
        try:
            year = int(year_str)
        except (ValueError, TypeError):
            continue

        if not (year_min <= year <= year_max):
            continue

        coalition_data = data.get(coalition, {})
        total = coalition_data.get("total", 0)
        if total < 1:
            continue

        total_weight += total
        total_aligned += coalition_data.get("aligned", 0)

    if total_weight < min_total:
        return None
    return round(total_aligned / total_weight * 100, 1)


def generate_site_data(legislators: dict, law_groups: dict) -> None:
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Legislators index
    skip_patterns = ("NO INCORPORADO", "PENDIENTE DE INCORPORACION", "A DESIGNAR")
    leg_index = []
    for key, leg in sorted(legislators.items(), key=lambda item: item[0]):
        name_upper = key.upper()
        if any(pattern in name_upper for pattern in skip_patterns) or key.strip(". ") == "":
            continue

        # Compute terms up front so the index can include coalition-specific totals.
        terms = compute_terms(leg)
        leg["_terms"] = terms

        alignment_pj = compute_weighted_alignment(leg["yearly_alignment"], "PJ")
        alignment_pro = compute_weighted_alignment(leg["yearly_alignment"], "PRO")
        alignment_lla = compute_weighted_alignment(leg["yearly_alignment"], "LLA")

        def _sum_aligned(coalition: str, min_total: int = 5):
            total_weight = 0
            total_aligned = 0
            for year_str, data in leg["yearly_alignment"].items():
                try:
                    year = int(year_str)
                except (ValueError, TypeError):
                    continue

                coalition_data = data.get(coalition, {})
                total = coalition_data.get("total", 0)
                if total < min_total:
                    continue
                if coalition == "UCR" and year > 2014:
                    continue
                if coalition in ("JxC", "PRO") and not (2015 <= year <= 2023):
                    continue
                if coalition == "LLA" and year < 2024:
                    continue

                total_weight += total
                total_aligned += coalition_data.get("aligned", 0)
            return total_aligned if total_weight > 0 else None

        votes_pj = _sum_aligned("PJ")
        votes_ucr = _sum_aligned("UCR")
        votes_pro = _sum_aligned("PRO")
        votes_lla = _sum_aligned("LLA")

        # Calculate presentismo only considering "En General" votes
        all_votes = leg.get("votes", [])
        en_general_votes = [v for v in all_votes if v.get("al") == "En General"]
        
        total_en_general = len(en_general_votes)
        ausente_en_general = sum(1 for v in en_general_votes if v.get("v") == "AUSENTE")
        
        # Apply trailing ausente logic only to En General votes
        trailing_ausente = _count_trailing_ausente(en_general_votes, leg.get("_terms") or terms)
        
        effective_total = total_en_general - trailing_ausente
        effective_ausente = ausente_en_general - trailing_ausente
        total_present = effective_total - effective_ausente
        presentismo_pct = round(total_present / effective_total * 100, 1) if effective_total > 0 else None

        # For ranking: use only En General votes for votaciones and ausencias counts
        # This matches the presentismo calculation which is also En General only
        all_votes = leg.get("votes", [])
        en_general_votes = [v for v in all_votes if v.get("al") == "En General"]
        total_en_general = len(en_general_votes)
        ausente_en_general = sum(1 for v in en_general_votes if v.get("v") == "AUSENTE")
        # Apply trailing ausente to En General votes
        trailing_ausente_ranking = _count_trailing_ausente(en_general_votes, leg.get("_terms") or terms)
        effective_ausente_ranking = ausente_en_general - trailing_ausente_ranking

        # Keep total votes count for reference (all votes, not just En General)
        total_votes = sum(stats.get("total", 0) for stats in leg["yearly_stats"].values())
        total_ausente = sum(stats.get("AUSENTE", 0) for stats in leg["yearly_stats"].values())
        total_abstencion = sum(stats.get("ABSTENCION", 0) for stats in leg["yearly_stats"].values())

        chambers = sorted(set(leg["chambers"]))
        chamber_display = (
            "+".join(chambers)
            if len(chambers) > 1
            else chambers[0]
            if chambers
            else leg["chamber"]
        )

        by_co = compute_per_coalition_alignment(terms, leg["yearly_alignment"], leg["yearly_stats"])

        if terms:
            # Use the electoral coalition from the most recent term
            latest_term = max(terms, key=lambda t: t["yt"])
            coalition_display = latest_term.get("co_electoral") or latest_term.get("co")
        else:
            coalition_display = leg["coalition"]

        display_name = _normalize_display_name(leg["name"])

        leg_index.append(
            {
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
                "tv": total_en_general,  # En General votes only
                "ph": leg.get("photo", ""),
                "pres": presentismo_pct,
                "aus": effective_ausente_ranking,  # En General ausentes only
                "abst": total_abstencion,
                "by_co": by_co,
            }
        )

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
        for year_str, data in sorted(leg["yearly_alignment"].items()):
            yearly_alignment_pct[year_str] = {}
            try:
                year = int(year_str)
            except Exception:
                year = None

            for coalition in ["PJ", "UCR", "JxC", "PRO", "LLA"]:
                total = data.get(coalition, {}).get("total", 0)
                aligned = data.get(coalition, {}).get("aligned", 0)
                pct = None

                # Apply year masks for opposition coalitions
                if coalition == "UCR":
                    if year is not None and year <= 2014:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                elif coalition in ("JxC", "PRO"):
                    if year is not None and 2015 <= year <= 2023:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                elif coalition == "LLA":
                    if year is not None and year >= 2024:
                        pct = round(aligned / total * 100, 1) if total > 5 else None
                    else:
                        pct = None
                else:
                    # PJ: always compute when enough votes
                    pct = round(aligned / total * 100, 1) if total > 5 else None

                yearly_alignment_pct[year_str][coalition] = pct

        # Build waffle groups — merge by common_name
        waffle_groups = defaultdict(lambda: {"name": "", "votes": [], "year": None, "common_name": None})
        for vote in leg["votes"]:
            law_name = vote.get("ln", "")
            # Determine merge key: use common_name if available, else gk.
            common_name = vote.get("cn") or (get_common_name(law_name) if law_name else None)
            if common_name:
                year = vote.get("yr", "")
                merge_key = f"COMMON|{common_name}|{year}" if year else f"COMMON|{common_name}"
            else:
                group_key = vote.get("gk", "")
                merge_key = group_key if group_key else f"SINGLE_{vote['vid']}"

            group = waffle_groups[merge_key]
            if not group["name"]:
                group["name"] = law_name or vote.get("t", "")
            if common_name:
                group["common_name"] = common_name
                group["name"] = common_name

            # Mark whether this is an "En General" vote
            article_label = vote.get("al", "")
            is_general = (
                article_label == "En General"
                or "EN GENERAL" in vote.get("t", "").upper()
                or "VOT. EN GRAL" in vote.get("t", "").upper()
            )

            entry = {
                "v": vote["v"],
                "al": article_label,
                "t": vote.get("t", ""),
                "d": vote.get("d", ""),
                "vid": vote.get("vid"),
                "ch": vote.get("ch"),
                "g": is_general,
            }
            if vote.get("url"):
                entry["url"] = vote["url"]
            group["votes"].append(entry)
            if vote.get("yr") and not group["year"]:
                group["year"] = vote["yr"]

        waffle_list = []
        for group_key, group in waffle_groups.items():
            # If a law group has multiple En General dictámenes, keep only the
            # approved one so the waffle shows the dictamen that was approved
            # overall, not the one this legislator personally voted for.
            general_votes = [vote for vote in group["votes"] if vote.get("g")]
            if len(general_votes) > 1:
                approved_generals = [vote for vote in general_votes if vote.get("eg")]
                chosen_general = approved_generals[0] if approved_generals else max(
                    general_votes, key=lambda vote: _parse_vote_date(vote.get("d", ""))
                )

                filtered_votes: list[dict] = []
                chosen_added = False
                for vote in group["votes"]:
                    if vote.get("g"):
                        if not chosen_added and vote is chosen_general:
                            filtered_votes.append(vote)
                            chosen_added = True
                    else:
                        filtered_votes.append(vote)
                group["votes"] = filtered_votes

            # Ensure at least one vote is marked g:True so the waffle always has a summary tile.
            if not any(v["g"] for v in group["votes"]):
                if len(group["votes"]) == 1:
                    group["votes"][0]["g"] = True

            # pick first available vote URL to act as law link
            law_url = ""
            for vote in group["votes"]:
                if vote.get("url"):
                    law_url = vote["url"]
                    break

            waffle_list.append(
                {
                    "gk": group_key,
                    "name": group["name"][:120],
                    "year": group["year"],
                    "url": law_url,
                    "votes": group["votes"],
                    "notable": group.get("common_name") is not None,
                }
            )

        def _waffle_latest_vote_ts(item: dict) -> int:
            latest = datetime.min
            for vote in item.get("votes", []):
                vote_date = _parse_vote_date(vote.get("d", ""))
                if vote_date > latest:
                    latest = vote_date
            if latest == datetime.min:
                return 0
            return int(latest.timestamp())

        waffle_list.sort(key=lambda item: (-_waffle_latest_vote_ts(item), item["name"]))

        leg_terms = leg.get("_terms") or compute_terms(leg)
        if leg_terms:
            # Use the electoral coalition from the most recent term
            latest_term = max(leg_terms, key=lambda t: t["yt"])
            detail_coalition = latest_term.get("co_electoral") or latest_term.get("co")
        else:
            detail_coalition = leg["coalition"]

        display_name = _normalize_display_name(leg["name"])

        # Calculate presentismo only considering "En General" votes (same as ranking)
        all_votes = leg.get("votes", [])
        en_general_votes = [v for v in all_votes if v.get("al") == "En General"]
        total_en_general = len(en_general_votes)
        ausente_en_general = sum(1 for v in en_general_votes if v.get("v") == "AUSENTE")
        trailing_ausente_detail = _count_trailing_ausente(en_general_votes, leg_terms)
        effective_total_detail = total_en_general - trailing_ausente_detail
        effective_ausente_detail = ausente_en_general - trailing_ausente_detail
        total_present_detail = effective_total_detail - effective_ausente_detail
        presentismo_detail = round(total_present_detail / effective_total_detail * 100, 1) if effective_total_detail > 0 else None

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
            "trailing_ausente": _count_trailing_ausente(leg.get("votes", []), leg_terms),
            "presentismo": presentismo_detail,
            "yearly_alignment": yearly_alignment_pct,
            "alignment": {coal: compute_weighted_alignment(leg["yearly_alignment"], coal) for coal in ["PJ", "UCR", "PRO", "JxC", "LLA"]},
            "era_alignment": {
                "1993-2014": {
                    "PJ": compute_era_alignment(leg["yearly_alignment"], "PJ", 1993, 2014),
                    "UCR": compute_era_alignment(leg["yearly_alignment"], "UCR", 1993, 2014),
                },
                "2015-2023": {
                    "PJ": compute_era_alignment(leg["yearly_alignment"], "PJ", 2015, 2023),
                    "PRO": compute_era_alignment(leg["yearly_alignment"], "PRO", 2015, 2023),
                },
                "2024-2026": {
                    "PJ": compute_era_alignment(leg["yearly_alignment"], "PJ", 2024, 2026),
                    "LLA": compute_era_alignment(leg["yearly_alignment"], "LLA", 2024, 2026),
                },
            },
            "terms": leg_terms,
            "votes": leg["votes"],
            "laws": waffle_list,
        }

        safe_name = re.sub(r"[^A-Z0-9_]", "_", key)[:80]
        write_start = time.time()
        save_json(leg_details_dir / f"{safe_name}.json", detail)
        write_elapsed = time.time() - write_start
        count += 1

        if count % 100 == 0 or count == total_legs:
            total_elapsed = time.time() - start_time
            log.info(
                f"Wrote {count}/{total_legs} legislator files; "
                f"last_write={write_elapsed:.2f}s; total_elapsed={total_elapsed:.2f}s"
            )

    log.info(f"Generated {len(legislators)} legislator detail files")

    # 3. Votaciones summary
    votaciones_summary = {"diputados": [], "senadores": []}
    for chamber in ["diputados", "senadores"]:
        votaciones = load_all_votaciones_from_db(chamber)
        for votacion in votaciones:
            votaciones_summary[chamber].append(
                {
                    "id": votacion.get("id"),
                    "title": votacion.get("title", "")[:200],
                    "date": clean_date(votacion.get("date", "")),
                    "result": votacion.get("result", ""),
                    "type": votacion.get("type", ""),
                    "afirmativo": votacion.get("afirmativo", 0),
                    "negativo": votacion.get("negativo", 0),
                    "abstencion": votacion.get("abstencion", 0),
                    "ausente": votacion.get("ausente", 0),
                }
            )

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
    for year, year_data in sorted(votes_by_year.items()):
        save_json(votes_dir / f"votes_{year}.json", year_data)
        total_votaciones += len(year_data["v"])
    log.info(f"Generated {len(votes_by_year)} per-year vote files ({total_votaciones} votaciones total)")

    # 4. Law names list
    law_names_set = set()
    for group in law_groups.values():
        common_name = group.get("common_name")
        if common_name:
            law_names_set.add(common_name)
        else:
            title = group.get("title", "").strip()
            if title and len(title) > 5:
                law_names_set.add(title[:120])
    save_json(DOCS_DATA_DIR / "law_names.json", sorted(law_names_set))
    log.info(f"Generated {len(law_names_set)} unique law names")

    # 5. Global stats (use leg_index count to exclude placeholder entries)
    stats = {
        "last_updated": datetime.now().isoformat(),
        "total_legislators": len(leg_index),
        "total_diputados": sum(1 for entry in leg_index if "diputados" in (entry.get("c") or "")),
        "total_senadores": sum(1 for entry in leg_index if "senadores" in (entry.get("c") or "")),
        "total_votaciones_diputados": len(votaciones_summary["diputados"]),
        "total_votaciones_senadores": len(votaciones_summary["senadores"]),
        "years_covered": sorted(set(year for leg in legislators.values() for year in leg["yearly_stats"].keys())),
        "years_diputados": list(
            practical_year_range(
                sorted(
                    set(
                        str(extract_year(votacion["date"]))
                        for votacion in votaciones_summary["diputados"]
                        if votacion.get("date") and extract_year(votacion["date"])
                    )
                )
            )
        ),
        "years_senadores": list(
            practical_year_range(
                sorted(
                    set(
                        str(extract_year(votacion["date"]))
                        for votacion in votaciones_summary["senadores"]
                        if votacion.get("date") and extract_year(votacion["date"])
                    )
                )
            )
        ),
        "total_laws": len(law_groups),
    }
    save_json(DOCS_DATA_DIR / "stats.json", stats)
    log.info("Generated global stats")

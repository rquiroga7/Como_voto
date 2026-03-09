#!/usr/bin/env python3
"""
Scrape Argentine legislative election data from Wikipedia.

Downloads per-district results from Wikipedia pages for every legislative
election from 1983 to 2023, extracts elected legislators and their
party/alliance, then classifies each by coalition (PJ, PRO, LLA, OTROS).

Output: data/election_legislators.json
Format:
{
  "2023": {
    "diputados": [
      {"name": "NOBLEGA, SEBASTIAN", "province": "Catamarca",
       "alliance": "Unión por la Patria", "coalition": "PJ"},
      ...
    ],
    "senadores": [...]
  },
  ...
}
"""

import json
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# All legislative election years (every 2 years, odd years since 1983)
ELECTION_YEARS = list(range(1983, 2025, 2))

# Wikipedia API endpoint for getting parsed HTML
WIKI_API = "https://es.wikipedia.org/w/api.php"

# Rate limit: seconds between requests
RATE_LIMIT = 1.0

# ---------------------------------------------------------------------------
# Alliance → Coalition classification
# ---------------------------------------------------------------------------

# Comprehensive mapping of alliance/party keywords to coalitions.
# Priority order: exact matches first, then keywords.

# PJ-affiliated alliances across all election years
_PJ_ALLIANCES = {
    # Modern era (2003+)
    "frente para la victoria", "frente de todos", "unión por la patria",
    "frente justicialista para la victoria", "frente justicialista",
    "partido justicialista", "frente cívico por santiago",
    "frente cívico y social", "frente cívico y social de catamarca",
    "frente renovador de la concordia", "frente de la concordia",
    "frente popular", "unión por córdoba", "concertación entrerriana",
    "frente justicialista popular", "frente justicialista federal",
    "frente de la victoria", "frente justicialista de unidad popular",
    "frente justicialista riojano", "frente justicialista popular santacruceño",
    "frente de la esperanza", "frente de unidad popular",
    "frente justicialista entrerriano", "frente justicialista para la victoria-unidad justicialista",
    "partido de la victoria", "frente cívico para la victoria",
    "unión por la patria", "unión por la patría",
    "más para entre ríos", "unión por san luis",
    "por santa cruz", "frente renovador de la concordia-innovación federal",
    "frente cívico por santiago",
    "hacemos por córdoba", "hacemos por nuestro país",
    "hacemos coalición federal",
    # CFK / Kirchnerismo vehicles
    "unidad ciudadana", "nuevo encuentro",
    # Frente de Todos variants
    "frente para todos", "frente todos", "frente con todos",
    # Provincial PJ alliances
    "compromiso federal", "compromiso con san juan",
    "frente popular bonaerense", "frente popular riojano",
    "frente popular salteño", "frente del pueblo riojano",
    "frente de unidad provincial", "frente de la unidad",
    "frente por la lealtad", "todos por entre ríos",
    "frente chaco merece más", "frente chubut para todos",
    "vamos con vos", "1país",
    "frente amplio formoseño",
    "frente entrerriano para la producción y el trabajo",
    "frente unión por buenos aires",
    "frente unión por san juan", "unidos por san juan",
    "frente social entre ríos tiene futuro",
    "frente somos mendoza",
    "fuerza de unidad popular",
    "frente movimiento popular",
    "frente movimiento vida y compromiso",
    "somos energía para renovar santa cruz",
    "unión por chaco", "unión para el nuevo chaco",
    "frente de integración social para un cambio en libertad",
    "movimiento solidario popular",
    "unidos por salta",
    # Classical PJ (pre-2003)
    "partido justicialista", "frente justicialista",
    "frente para la victoria",
}

_PJ_KEYWORDS = [
    "justicialista", "para la victoria", "frente de todos",
    "unión por la patria", "frente cívico por santiago",
    "frente cívico y social", "renovador de la concordia",
    "por santa cruz", "más para entre ríos", "unión por san luis",
    "unidad ciudadana", "chaco merece más", "chubut para todos",
]

# PRO/UCR/Cambiemos alliances
_PRO_ALLIANCES = {
    "alianza propuesta republicana", "propuesta republicana",
    "cambiemos", "juntos por el cambio",
    "compromiso para el cambio", "recrear para el crecimiento",
    "pro", "frente cambia mendoza", "frente cambia jujuy",
    "juntos por entre ríos", "juntos por el cambio chubut",
    "cambia santa cruz", "juntos por el cambio tierra del fuego",
    "eco + vamos corrientes", "encuentro por corrientes",
    "encuentro por corrientes-eco + vamos corrientes",
    "buenos aires por el cambio",
    "juntos", "vamos juntos", "unión pro",
    "juntos podemos más",
    "vamos juntos (cambiemos)",
    "unión pro santa fe federal",
    "frente demócrata - unión pro",
    "frente unión pro -dignidad",
    "unión para vivir mejor", "vamos todos a vivir mejor",
    "evolución",
    "juntos somos río negro", "juntos somos rio negro",
    "juntos por formosa libre", "juntos por la rioja",
    "frente compromiso para el cambio",
}

_PRO_KEYWORDS = [
    "juntos por el cambio", "cambiemos", "propuesta republicana",
    "cambia mendoza", "cambia jujuy", "cambia santa cruz",
    "juntos por entre ríos", "unión pro",
]

# UCR-affiliated alliances (standalone UCR, ARI, CC, Alianza-era)
_UCR_ALLIANCES = {
    "unión cívica radical", "alianza",
    "alianza trabajo, justicia y educación",
    "alianza para el trabajo, la justicia y la educación",
    "frente de todos",  # 2005 Corrientes, UCR-led
    "concertación para el desarrollo",
    "frente jujeño", "frente jujeño justicialista",
    "frente progresista cívico y social",
    "encuentro por córdoba",
    "acuerdo cívico y social", "frente acuerdo cívico y social",
    "frente amplio unen", "frente cívico jujeño",
    "frente pampeano cívico y social", "propuesta frente pampeano cívico y social",
    "cambia neuquén",
    "frente para el cambio",
    "frente ciudadano y social",
    "frente fundacional para el cambio",
}

_UCR_KEYWORDS = [
    "unión cívica radical", "u.c.r.", "ucr",
]

# LLA alliances
_LLA_ALLIANCES = {
    "la libertad avanza", "avanza libertad",
    "ahora patria", "fuerza republicana",
    "partido renovador federal",
    "arriba neuquén", "partido fe",
    "republicanos unidos",
}

_LLA_KEYWORDS = [
    "libertad avanza", "avanza libertad",
]

# Parties/alliances that are clearly "OTROS"
_OTROS_ALLIANCES = {
    "frente de izquierda", "frente de izquierda y de trabajadores",
    "frente de izquierda y de trabajadores - unidad",
    "movimiento popular neuquino", "somos fueguinos",
    "movimiento popular fueguino", "movimiento popular jujeño",
    "la fuerza de santa fe",
    "partido demócrata progresista", "partido demócrata de mendoza",
    "unión del centro democrático",
    "movimiento por la dignidad y la independencia",
    "frepaso", "frente país solidario",
    "acción chaqueña", "partido renovador de salta",
    "unidad socialista", "partido socialista",
    "partido bloquista", "cruzada renovadora",
    "pacto autonomista - liberal", "pacto autonomista-liberal",
    "movimiento cristiano independiente",
    "fuerza republicana",  # Tucumán 1993-2005, pre-LLA
    "partido socialista auténtico",
    "confederación vecinal",
    "convocatoria independiente",
    "frente nuevo",  # Córdoba 2005, Juez party
    "partido demócrata cristiano",
}


def classify_party_code(code: str, year: int) -> str | None:
    """Classify a per-candidate party code into a coalition.

    Party codes appear in parentheses after candidate names, e.g. "(PJ)",
    "(UCR)", "(PJ-FPV)", "(PS)".  Returns a coalition label or None if the
    code is not recognized (so the caller can fall back to alliance-level
    classification).
    """
    if not code:
        return None
    c = code.upper().strip().replace(' ', '')

    # PJ-affiliated codes
    if c in ("PJ", "PJ-FPV", "PJ-FPV", "PJ-FPV", "FPV", "FPV-PJ", "FREJUVI",
             "FREJULI",
             "PJ-FS", "PJ-HACER", "PJ-KOLINA", "PJ-LC", "PJ-LSL",
             "PJ-PCS", "PJ-PXC", "PJ-UPTDF", "PJ-UYO",
             "PJS", "IND.-PJ", "KOLINA", "FORJA", "NE", "PTP-PCR"):
        return "PJ"

    # UCR codes
    if c in ("UCR", "U.C.R."):
        return "UCR"

    # PRO codes (from 2003+)
    if c in ("PRO", "CC-ARI", "CC", "CXC", "MID-PRO"):
        return "PRO" if year >= 2003 else "OTROS"

    # LLA codes
    if c in ("LLA",):
        return "LLA" if year >= 2021 else "OTROS"

    # Codes that map to OTROS regardless of era
    if c in ("PS", "PSA", "PSP", "PSD", "PSOL", "PSUR",
             "PSD-FREPASO", "SI", "SI-FG",
             "PI", "PC", "PO", "PBT", "MST", "PTS", "PH",
             "MPN", "MAS", "PDC", "PDP", "PD", "MODIN",
             "ARI", "PAUFE", "FR", "MOPOF", "PRS",
             "MID", "FG", "FREPASO", "UCEDE", "UCEDÉ",
             "GEN", "MOVERE", "MIJD",
             "PB", "PL", "PN", "PP", "PPC", "PPS",
             "UCYB", "UP", "UXT", "UNIR", "UNITE",
             "ADN", "AF", "AP", "CR", "EP", "FL",
             "RU", "SER", "SST", "SNU",
             "BAPT", "CHUSOTO", "CET", "FCC", "FCYS",
             "FE", "FEF", "FTNP", "FPG", "LTP", "LDS",
             "MNA", "NP", "P3P", "PAIS", "PARES", "PAYS",
             "PCP", "PCS", "PDV", "PD-VYF", "PRFTU",
             "PARTE", "PDD", "PDF", "PROCOR", "PYT", "USPV",
             "UPL", "1RN", "3P", "ERF", "CP"):
        return "OTROS"

    # Not recognized — let caller fall back to alliance classification
    return None


def classify_alliance(alliance_name: str, year: int) -> str:
    """Classify an electoral alliance into a coalition bucket.

    Uses year to adjust classification (e.g. Fuerza Republicana was
    OTROS before 2021, but allied with LLA in 2023).
    """
    name = alliance_name.lower().strip()

    # Check for LLA parenthetical annotation like "Partido Fe (La Libertad Avanza)"
    if "(la libertad avanza)" in name:
        return "LLA"
    # Check for UxP parenthetical
    if "(unión por la patria)" in name:
        return "PJ"
    if "(hacemos por nuestro país)" in name:
        return "OTROS"

    # Remove parenthetical annotations for keyword matching
    clean = re.sub(r'\s*\(.*?\)\s*', ' ', name).strip()
    clean = re.sub(r'\s+', ' ', clean)

    # --- LLA (only exists from 2021+) ---
    if year >= 2021:
        for kw in _LLA_KEYWORDS:
            if kw in clean:
                return "LLA"
        if clean in _LLA_ALLIANCES:
            return "LLA"
        # Fuerza Republicana allied with LLA in 2023
        if year >= 2023 and "fuerza republicana" in clean:
            return "LLA"
        # Partido Renovador Federal allied with LLA in 2023
        if year >= 2023 and "partido renovador federal" in clean:
            return "LLA"
        # Ahora Patria (Salta) allied with LLA in 2023
        if year >= 2023 and "ahora patria" in clean:
            return "LLA"
        if year >= 2023 and "arriba neuquén" in clean:
            return "LLA"
        if year >= 2023 and "partido fe" in clean:
            return "LLA"
        if year >= 2023 and "republicanos unidos" in clean:
            return "LLA"

    # --- PJ ---
    for kw in _PJ_KEYWORDS:
        if kw in clean:
            return "PJ"
    if clean in _PJ_ALLIANCES:
        return "PJ"

    # --- UCR alliances (always returns UCR; era remapping done later) ---
    if clean in _UCR_ALLIANCES:
        return "UCR"
    for kw in _UCR_KEYWORDS:
        if kw in clean:
            return "UCR"
    if "alianza" in clean and year >= 1997 and year <= 2003:
        return "UCR"  # Alianza was UCR-led

    # --- PRO/Cambiemos/JxC (from 2003+) ---
    if year >= 2003:
        for kw in _PRO_KEYWORDS:
            if kw in clean:
                return "PRO"
        if clean in _PRO_ALLIANCES:
            return "PRO"

    # --- Specific OTROS checks ---
    if clean in _OTROS_ALLIANCES:
        return "OTROS"

    # --- Fallback keywords ---
    if "peronist" in clean or "justiciali" in clean:
        return "PJ"

    return "OTROS"


# ---------------------------------------------------------------------------
# Wikipedia HTML parsing
# ---------------------------------------------------------------------------

def fetch_wiki_html(page_title: str) -> str | None:
    """Fetch the parsed HTML of a Wikipedia page via the API."""
    params = {
        "action": "parse",
        "page": page_title,
        "format": "json",
        "prop": "text",
        "disablelimitreport": "true",
        "disableeditsection": "true",
    }
    headers = {"User-Agent": "ComoVotoBot/1.0 (election data scraper for civic project)"}
    try:
        r = requests.get(WIKI_API, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "parse" in data and "text" in data["parse"]:
            return data["parse"]["text"]["*"]
    except Exception as e:
        print(f"  Error fetching {page_title}: {e}")
    return None


def extract_province_name(header_text: str) -> str:
    """Extract province name from header like 'Provincia de Buenos Aires 35 Diputados'."""
    text = header_text.strip()
    # Remove "Territorio nacional de la" prefix (Tierra del Fuego pre-1990)
    text = re.sub(r'^\s*Territorio\s+nacional\s+de\s+la?\s*', '', text, flags=re.I)
    # Remove "Provincia del" (e.g. "Provincia del Chaco")
    text = re.sub(r'^\s*Provincia\s+del\s+', '', text, flags=re.I)
    # Remove "Provincia de" (e.g. "Provincia de Buenos Aires", "Provincia de La Pampa")
    text = re.sub(r'^\s*Provincia\s+de\s+', '', text, flags=re.I)
    # Handle "Ciudad Autónoma de Buenos Aires" / "Ciudad de Buenos Aires"
    text = re.sub(r'^\s*Ciudad\s+(Autónoma\s+)?de\s+', '', text, flags=re.I)
    # Remove trailing "N Diputados/Senadores" + optional "Mandato: YYYY-YYYY"
    text = re.sub(r'\s+\d+\s+(Diputados?|Senadores?)(\s+Mandato:\s+\d{4}-\d{4})?\s*$', '', text, flags=re.I)
    # Remove Antarctic territory suffix
    text = re.sub(r',?\s*Antártida e Islas del Atlántico Sur', '', text, flags=re.I)
    # Remove footnote markers like "[8]", "[ 8 ]", "[nota 1]" and zero-width spaces
    text = re.sub(r'\s*\[.*?\]\s*', '', text)
    text = re.sub(r'\s*\u200b\s*', '', text)
    # Normalize "Capital Federal" → "Capital Federal" for compatibility
    if text.strip().lower() in ('capital federal', 'buenos aires') and 'Capital' in header_text:
        return 'Capital Federal'
    return text.strip()


def extract_alliance_name(cell) -> str:
    """Extract alliance name from the alliance cell, stripping party listings."""
    text = cell.get_text(' ', strip=True)
    # Truncate at "Ver partidos"/"Ver candidatos"/"Ver electos"
    text = re.split(r'\s*Ver\s+(partidos|candidatos|electos)', text, flags=re.I)[0].strip()
    # Remove parenthetical abbreviations like "(UCR)", "(FREJUFE)"
    # But keep complex names like "Frente Justicialista Federal (FREJUFE)"
    # Only remove trailing short abbreviations
    text = re.sub(r'\s*\([A-Z]{2,10}\)\s*$', '', text).strip()
    return text


def _extract_party_code(text: str) -> str | None:
    """Extract a party code from parenthetical annotation in candidate text.

    Looks for patterns like "(PJ)", "(UCR)", "(PJ-FPV)", "(PS)" etc.
    Returns the code string or None if not found.
    """
    # Find ALL parenthetical annotations and pick the one that looks like
    # a party code (uppercase, short, contains hyphens/dots).
    for m in re.finditer(r'\(([^)]+)\)', text):
        code = m.group(1).strip()
        # Skip long text, descriptions, footnote references
        if len(code) > 20 or len(code) < 2:
            continue
        # Skip quoted nicknames like ("Nacha Guevara")
        if '"' in code or '\u201c' in code or '\u201d' in code:
            continue
        # Skip lowercase-starting words like "(hijo)", "(h)", "(mostrar)"
        if code[0].islower():
            continue
        # Skip purely numeric like "(1)" or date-like
        if re.match(r'^[\d.,\s]+$', code):
            continue
        # Must contain at least one uppercase letter
        if not re.search(r'[A-Z]', code):
            continue
        # Skip known non-party annotations
        if code.lower() in ('la libertad avanza', 'unión por la patria',
                            'hacemos por nuestro país'):
            continue
        return code
    return None


def extract_elected_from_cell(cell, seats_won: int) -> list[tuple[str, str | None, bool]]:
    """Extract candidate names from a candidates cell.

    Uses <li> elements with <img alt="Sí"> for modern pages.
    Falls back to all <li> text for older pages without checkmarks.

    Returns list of (name, party_code, is_suplente) tuples.
    """
    lis = cell.find_all('li')
    if not lis:
        # No list items - try plain text parsing
        text = cell.get_text('\n', strip=True)
        text = re.sub(r'Ver\s+(candidatos|electos)\s*:', '', text, flags=re.I).strip()
        results = []
        for line in text.split('\n'):
            line = line.strip()
            if not line or re.match(r'^[\d.,\s%]+$', line):
                continue
            # Extract party code before stripping annotations
            party_code = _extract_party_code(line)
            # Remove party annotations and footnotes
            name = re.sub(r'\s*\([^)]*\)\s*', ' ', line).strip()
            name = re.sub(r'\[.*?\]', '', name).strip()
            name = re.sub(r'\s*​\s*', '', name).strip()  # zero-width space
            if name and len(name) > 2:
                results.append((name, party_code, False))
        return results[:seats_won] if seats_won > 0 else results

    # Has <li> elements - check for Sí checkmarks
    elected = []
    all_entries = []

    for li in lis:
        # Check for elected marker: <img alt="Sí"> or <span title="Sí">
        is_elected = bool(
            li.find('img', alt='Sí') or li.find('span', title='Sí')
        )

        # Get the FULL li text for party code extraction (code may be
        # outside the bold span, e.g. "<b>Oscar Aguad</b> (UCR)")
        full_li_text = li.get_text(' ', strip=True)

        # Extract name from the full text content, not from <a> tags
        # (which sometimes link to party pages instead of person pages)
        raw_text = None
        # Look for bold span (elected names are bold in modern pages)
        bold = li.find('span', style=lambda s: s and 'bold' in s)
        if bold:
            raw_text = bold.get_text(' ', strip=True)
        else:
            raw_text = full_li_text

        if not raw_text:
            continue

        # Extract party code from full li text (may be outside bold span)
        party_code = _extract_party_code(full_li_text)

        # Clean name: remove party annotations, footnotes, etc.
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', raw_text).strip()
        name = re.sub(r'\[.*?\]', '', name).strip()
        name = re.sub(r'\s*​\s*', '', name).strip()  # zero-width space
        name = name.strip('.')

        if not name or len(name) < 2:
            continue

        all_entries.append((name, party_code, is_elected))
        if is_elected:
            elected.append((name, party_code))

    # If we found Sí markers, return elected + suplentes
    if elected:
        elected_set = set(elected)
        result = [(n, pc, False) for n, pc in elected]
        result += [(n, pc, True) for n, pc, was_elected in all_entries
                   if (n, pc) not in elected_set]
        return result
    # Otherwise, all listed are assumed elected (older format)
    trimmed = all_entries[:seats_won] if seats_won > 0 else all_entries
    return [(n, pc, False) for n, pc, _ in trimmed]


def parse_election_page(html: str, year: int) -> dict:
    """Parse a Wikipedia election page and extract elected legislators.

    Returns {"diputados": [...], "senadores": [...]}
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"diputados": [], "senadores": []}

    for table in soup.find_all("table", class_="wikitable"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Check if this is a per-district results table
        # First row should be a province header with "N Diputados" or "N Senadores"
        first_text = rows[0].get_text(' ', strip=True)
        if not re.search(r'\d+\s+(Diputados?|Senadores?)', first_text, re.I):
            continue

        # Skip "Electores de Senador" tables (pre-2001 electoral college)
        if re.search(r'Electores?\s+de\s+Senad', first_text, re.I):
            continue

        # Process this table - walk through rows
        province = None
        chamber = None

        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue

            first_cell = cells[0]
            colspan = int(first_cell.get('colspan') or 1)
            cell_text = first_cell.get_text(' ', strip=True)

            # Province header: single cell with large colspan
            if colspan >= 5 and re.search(r'\d+\s+(Diputados?|Senadores?)', cell_text, re.I):
                province = extract_province_name(cell_text)
                if re.search(r'Senadores?', cell_text, re.I):
                    chamber = "senadores"
                else:
                    chamber = "diputados"
                continue

            if not province or not chamber:
                continue

            # Skip rows with fewer than 6 cells (headers, bars, summaries)
            if len(cells) < 6:
                continue

            # Find the bancas cell (format X/Y)
            bancas_idx = None
            seats_won = 0
            for i, c in enumerate(cells):
                t = c.get_text(strip=True)
                m = re.match(r'^(\d+)/(\d+)$', t)
                if m:
                    bancas_idx = i
                    seats_won = int(m.group(1))
                    break

            if bancas_idx is None or seats_won == 0:
                continue

            # Alliance name: usually in cell[1], but if that's a number
            # (vote count), try cell[0] instead (some older tables lack
            # the color-bar column so cell indices shift).
            if len(cells) < 2:
                continue
            # Skip summary rows (bgcolor='coral', 'pink', etc.)
            row_bgcolor = (row.get('bgcolor') or '').lower()
            if row_bgcolor in ('coral', 'pink', 'gray', 'grey', '#cccccc'):
                continue

            alliance_name = extract_alliance_name(cells[1])
            if not alliance_name or re.match(r'^[\d.,\s]+$', alliance_name):
                # cell[1] was a vote count — try cell[0]
                alliance_name = extract_alliance_name(cells[0])
            if not alliance_name or re.match(r'^[\d.,\s]+$', alliance_name):
                continue

            # Skip summary / total rows parsed as alliances
            alliance_lower = alliance_name.lower().strip()
            if re.match(r'^total\b', alliance_lower):
                continue

            # Candidate cells: all cells after the bancas cell
            candidates = []
            for ci in range(bancas_idx + 1, len(cells)):
                candidates.extend(extract_elected_from_cell(cells[ci], seats_won))

            alliance_coalition = classify_alliance(alliance_name, year)

            for cand_name, party_code, is_suplente in candidates:
                if cand_name.strip():
                    # Party code is primary when it identifies a major coalition;
                    # if it returns OTROS (= unrecognized minor party), prefer
                    # the alliance-level classification instead.
                    pc_coalition = classify_party_code(party_code, year) if party_code else None
                    if pc_coalition and pc_coalition != "OTROS":
                        coalition = pc_coalition
                    else:
                        coalition = alliance_coalition

                    entry = {
                        "name": cand_name.strip(),
                        "province": province,
                        "alliance": alliance_name,
                        "coalition": coalition,
                        "party_code": party_code,
                    }
                    if is_suplente:
                        entry["suplente"] = True
                    result[chamber].append(entry)

    return result


def scrape_all_elections() -> dict:
    """Scrape all election years from Wikipedia."""
    all_data = {}

    for year in ELECTION_YEARS:
        print(f"\n{'='*60}")
        print(f"Processing year {year}...")
        print(f"{'='*60}")

        # Try different page title patterns
        page_titles = [
            f"Elecciones_legislativas_de_Argentina_de_{year}",
        ]

        html = None
        for title in page_titles:
            print(f"  Trying: {title}")
            html = fetch_wiki_html(title)
            if html:
                print(f"  ✓ Found page")
                break
            time.sleep(RATE_LIMIT)

        if not html:
            print(f"  ✗ No page found for {year}")
            all_data[str(year)] = {"diputados": [], "senadores": []}
            continue

        data = parse_election_page(html, year)

        n_dip = len(data["diputados"])
        n_sen = len(data["senadores"])
        print(f"  Extracted: {n_dip} diputados, {n_sen} senadores")

        # Show coalition breakdown
        for chamber in ["diputados", "senadores"]:
            if data[chamber]:
                coalitions = {}
                for leg in data[chamber]:
                    co = leg["coalition"]
                    coalitions[co] = coalitions.get(co, 0) + 1
                print(f"    {chamber}: {coalitions}")

        all_data[str(year)] = data
        time.sleep(RATE_LIMIT)

    return all_data


def main():
    print("Scraping Argentine legislative election data from Wikipedia...")
    print(f"Years: {ELECTION_YEARS[0]}-{ELECTION_YEARS[-1]}")

    data = scrape_all_elections()

    # Save
    output_path = DATA_DIR / "election_legislators.json"
    DATA_DIR.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total = 0
    for year in sorted(data.keys()):
        n_dip = len(data[year]["diputados"])
        n_sen = len(data[year]["senadores"])
        print(f"  {year}: {n_dip} dip + {n_sen} sen = {n_dip + n_sen}")
        total += n_dip + n_sen
    print(f"  TOTAL: {total} legislator-elections")
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Como Voto - Data Scraper
========================
Scrapes voting data from:
  - Diputados: https://votaciones.hcdn.gob.ar/  (IDs 1-6500)
  - Senadores: https://www.senado.gob.ar/votaciones/actas

Also scrapes legislator photos:
  - Diputados photos from voting page tables
  - Senadores photos from the Senado open data JSON API
  - Wikipedia/Wikidata fallback for legislators without official photos

Stores results in data/ directory as consolidated JSON files
(one file per chamber with shared lookup tables for compact storage).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import logging
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FOTOS_DIR = BASE_DIR / "docs" / "fotos"

HCDN_BASE = "https://votaciones.hcdn.gob.ar"
SENADO_BASE = "https://www.senado.gob.ar"

# Rate-limiting: seconds between requests
REQUEST_DELAY = 0.3

# Some HCDN IDs return 500 from the plain /votacion/{id} URL but work with a
# slug prefix.  Map id -> full URL path (slug + id) for those cases.
# These are manually confirmed; the scraper also auto-discovers slugs at runtime.
HCDN_SLUG_OVERRIDES: dict[str, str] = {
    "393": f"{HCDN_BASE}/votacion/derecho-identidad-genero-general/393",
    "394": f"{HCDN_BASE}/votacion/derecho-identidad-genero-articulo-5/394",
    "395": f"{HCDN_BASE}/votacion/derecho-identidad-genero-articulo-11/395",
}

# Spanish stop-words stripped when building slug candidates from expedition titles
_SLUG_STOP_WORDS = {
    "a", "al", "de", "del", "la", "las", "el", "los", "en", "con",
    "por", "sobre", "para", "y", "o", "e", "que", "se", "un", "una",
    "unos", "unas", "su", "sus", "lo", "le", "les", "nos",
}


def _slugify(text: str, max_words: int = 4) -> str:
    """Convert a Spanish law title into an HCDN-style URL slug.

    - Strip text after the first ':' (description/modifier part)
    - Normalize Unicode → ASCII
    - Remove stop words and short tokens
    - Join first *max_words* significant words with hyphens
    """
    import unicodedata as _ud
    # Only use the part before a colon (law name, not description)
    text = text.split(":")[0]
    text = _ud.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if w and w not in _SLUG_STOP_WORDS and len(w) > 1]
    return "-".join(words[:max_words])


# Cache for the id→slug map built from HCDN year-based search pages.
# Populated lazily on first call to _get_slug_map().
_SLUG_MAP: dict[str, str] | None = None


def _fetch_hcdn_slug_map() -> dict[str, str]:
    """Scrape /votaciones/search for every year to build a complete id→slug map.

    The HCDN search page embeds  redirectActa(id, hasVote, 'slug')  in every
    row's onclick.  Older sessions (≈ 2008-2019) require a slug prefix in the
    URL; newer ones have an empty slug and work with the bare /votacion/{id}
    path.  We record both so callers can distinguish the two cases.

    Returns: dict mapping str(id) -> slug string (empty string = bare URL).
    """
    slug_map: dict[str, str] = {}
    current_year = datetime.now().year
    for year in range(1993, current_year + 1):
        try:
            resp = SESSION.post(
                f"{HCDN_BASE}/votaciones/search",
                data={"txtSearch": "", "anoSearch": str(year)},
                timeout=20,
            )
            matches = re.findall(
                r"redirectActa\((\d+),(\d+),'([^']*)'\)", resp.text
            )
            for vid, _, slug in matches:
                slug_map[vid] = slug
            log.info(f"  Slug map: {year}: {len(matches)} rows")
        except Exception as exc:
            log.warning(f"  Slug map: {year} failed: {exc}")
        time.sleep(REQUEST_DELAY)
    with_slug = sum(1 for v in slug_map.values() if v)
    log.info(
        f"Slug map ready: {len(slug_map)} IDs total, {with_slug} require slug URLs"
    )
    return slug_map


def _get_slug_map() -> dict[str, str]:
    """Return the cached id→slug map, building it on the first call."""
    global _SLUG_MAP
    if _SLUG_MAP is None:
        log.info("Building HCDN slug map from search pages (one-time) ...")
        _SLUG_MAP = _fetch_hcdn_slug_map()
    return _SLUG_MAP


def _find_slug_url(votacion_id: str) -> str | None:
    """Return the correct URL for an HCDN vote ID that returns HTTP 500.

    Strategy:
    1. Look up the pre-built slug map (populated from /votaciones/search pages).
       - If the ID is in the map with a non-empty slug → return slug URL.
       - If the ID is in the map with an empty slug → bare URL should work;
         return None so the caller gives up (avoids redundant network calls).
    2. For IDs not yet in the map (very new sessions scraped before the map was
       refreshed), fall back to the ajax/expedientes title-guessing approach.
    """
    slug_map = _get_slug_map()

    if votacion_id in slug_map:
        slug = slug_map[votacion_id]
        if slug:
            url = f"{HCDN_BASE}/votacion/{slug}/{votacion_id}"
            log.info(f"  [{votacion_id}] Slug URL from map: {url}")
            return url
        # Empty slug → the site says bare URL should work; nothing more to try.
        return None

    # ── Fallback: ID not in map (very recent or edge case) ──────────────────
    # Use ajax/expedientes to get the title, then guess the slug.
    log.debug(f"  [{votacion_id}] Not in slug map; trying ajax/expedientes")
    try:
        r = SESSION.post(
            f"{HCDN_BASE}/ajax/expedientes",
            data={"id-acta": votacion_id, "texto": ""},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
    except Exception:
        return None

    if not payload.get("success") or not payload.get("expedientes"):
        return None  # ID genuinely doesn't exist

    title = payload["expedientes"][0].get("titulo", "")
    if not title:
        return None

    bases = []
    for nw in (3, 4):
        b = _slugify(title, max_words=nw)
        if b and b not in bases:
            bases.append(b)

    vote_suffixes = [
        "", "general", "particular", "en-general", "en-particular",
    ] + [f"articulo-{n}" for n in range(1, 21)]

    for base in bases:
        for suffix in vote_suffixes:
            slug = f"{base}-{suffix}" if suffix else base
            url = f"{HCDN_BASE}/votacion/{slug}/{votacion_id}"
            try:
                resp = SESSION.get(url, timeout=8)
                if resp.status_code == 200 and "¿CÓMO VOTÓ?" in resp.text:
                    log.info(f"  [{votacion_id}] Discovered slug URL: {url}")
                    return url
            except Exception:
                pass
            time.sleep(REQUEST_DELAY)

    log.warning(f"  [{votacion_id}] Could not find slug URL (title: {title[:60]})")
    return None

# Senado periods to scrape
# Available on website: 2005 onwards (earlier years have no digital records)
SENADO_YEARS = list(range(2005, datetime.now().year + 1))

# Vote code mapping (compact integer codes for storage)
VOTE_ENCODE = {
    "AFIRMATIVO": 1,
    "NEGATIVO": 2,
    "ABSTENCION": 3,
    "AUSENTE": 4,
    "PRESIDENTE": 5,
}
VOTE_DECODE = {v: k for k, v in VOTE_ENCODE.items()}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scraper")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ComoVoto-Scraper/2.0 (https://github.com/rquiroga7/Como_voto; educational project)",
    "Accept-Language": "es-AR,es;q=0.9",
})

# ---------------------------------------------------------------------------
# Party classification helpers
# ---------------------------------------------------------------------------
PJ_KEYWORDS = [
    "justicialista", "frente de todos", "frente para la victoria",
    "unión por la patria", "union por la patria",
    "frente renovador", "peronismo", "peronista",
    "frente cívico por santiago", "frente civico por santiago",
    "movimiento popular neuquino",
    "bloque justicialista", "pj ",
]

PRO_KEYWORDS = [
    "pro ", "propuesta republicana",
    "cambiemos", "juntos por el cambio", "juntos por el cambio federal",
    "ucr", "unión cívica radical", "union civica radical",
    "coalición cívica", "coalicion civica",
    "evolución radical", "evolucion radical",
]

LLA_KEYWORDS = [
    "la libertad avanza",
]


def classify_bloc(bloc_name: str) -> str:
    """Classify a bloc name into PJ, PRO, LLA or OTHER."""
    name = bloc_name.lower().strip()
    for kw in PJ_KEYWORDS:
        if kw in name:
            return "PJ"
    for kw in PRO_KEYWORDS:
        if kw in name:
            return "PRO"
    for kw in LLA_KEYWORDS:
        if kw in name:
            return "LLA"
    return "OTROS"


# ---------------------------------------------------------------------------
# Consolidated JSON Database
# ---------------------------------------------------------------------------

class ConsolidatedDB:
    """Manages a consolidated JSON database for a chamber.

    Format on disk (compact JSON, no whitespace):
    {
      "names": ["Name1", "Name2", ...],
      "blocs": ["Bloc1", "Bloc2", ...],
      "provinces": ["Prov1", "Prov2", ...],
      "photo_ids": {"0": "A1234", ...},     // str(name_idx) -> photo_id
      "votaciones": [
        {
          "id": "123",
          "t": "Title",
          "d": "01/01/2015 - 14:30",
          "r": "AFIRMATIVO",
          "tp": "EN GENERAL",
          "p": "Período ...",
          "a": 200, "n": 30, "b": 5, "u": 22,
          "v": [[name_idx, bloc_idx, prov_idx, vote_code], ...]
        }, ...
      ]
    }

    vote_code: 1=AFIRMATIVO, 2=NEGATIVO, 3=ABSTENCION, 4=AUSENTE, 5=PRESIDENTE
    """

    def __init__(self, path: Path):
        self.path = path
        self.names: list[str] = []
        self.blocs: list[str] = []
        self.provinces: list[str] = []
        self.photo_ids: dict[str, str] = {}  # str(name_idx) -> photo_id
        self.votaciones: list[dict] = []
        self._name_idx: dict[str, int] = {}
        self._bloc_idx: dict[str, int] = {}
        self._prov_idx: dict[str, int] = {}
        self._votacion_ids: set[str] = set()

    def load(self):
        """Load existing data from disk."""
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Error loading {self.path}: {e}")
            return

        self.names = data.get("names", [])
        self.blocs = data.get("blocs", [])
        self.provinces = data.get("provinces", [])
        self.photo_ids = data.get("photo_ids", {})
        self.votaciones = data.get("votaciones", [])

        # Rebuild indexes
        self._name_idx = {n: i for i, n in enumerate(self.names)}
        self._bloc_idx = {b: i for i, b in enumerate(self.blocs)}
        self._prov_idx = {p: i for i, p in enumerate(self.provinces)}
        self._votacion_ids = {str(v["id"]) for v in self.votaciones}

    def save(self):
        """Save to disk (compact JSON, no indent)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "names": self.names,
            "blocs": self.blocs,
            "provinces": self.provinces,
            "photo_ids": self.photo_ids,
            "votaciones": self.votaciones,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    def has_votacion(self, vid: str) -> bool:
        return str(vid) in self._votacion_ids

    def _get_name_idx(self, name: str) -> int:
        if name not in self._name_idx:
            idx = len(self.names)
            self.names.append(name)
            self._name_idx[name] = idx
        return self._name_idx[name]

    def _get_bloc_idx(self, bloc: str) -> int:
        if bloc not in self._bloc_idx:
            idx = len(self.blocs)
            self.blocs.append(bloc)
            self._bloc_idx[bloc] = idx
        return self._bloc_idx[bloc]

    def _get_prov_idx(self, province: str) -> int:
        if province not in self._prov_idx:
            idx = len(self.provinces)
            self.provinces.append(province)
            self._prov_idx[province] = idx
        return self._prov_idx[province]

    def add_votacion(self, raw: dict):
        """Add a votacion in the raw (expanded) format, converting to compact."""
        vid = str(raw.get("id", ""))
        if vid in self._votacion_ids:
            return  # already have it

        compact_votes = []
        for v in raw.get("votes", []):
            name = v.get("name", "").strip()
            if not name:
                continue
            ni = self._get_name_idx(name)
            bi = self._get_bloc_idx(v.get("bloc", ""))
            pi = self._get_prov_idx(v.get("province", ""))
            vc = VOTE_ENCODE.get(v.get("vote", "").upper(), 0)
            compact_votes.append([ni, bi, pi, vc])

            # Track photo_id
            photo_id = v.get("photo_id", "")
            if photo_id:
                self.photo_ids[str(ni)] = photo_id

        entry = {
            "id": vid,
            "t": raw.get("title", ""),
            "d": raw.get("date", ""),
            "r": raw.get("result", ""),
            "tp": raw.get("type", ""),
            "p": raw.get("period", ""),
            "a": raw.get("afirmativo", 0),
            "n": raw.get("negativo", 0),
            "b": raw.get("abstencion", 0),
            "u": raw.get("ausente", 0),
            "v": compact_votes,
        }
        # Extract and save the slug from the fetched URL so expand_votacion
        # can reconstruct the correct link without re-hitting the slug map.
        # URL shape: .../votacion/{slug}/{id}  → save slug; bare .../votacion/{id} → save ""
        raw_url = raw.get("url", "")
        slug_m = re.search(r"/votacion/([^/]+)/\d+$", raw_url)
        if slug_m:
            entry["sl"] = slug_m.group(1)
        self.votaciones.append(entry)
        self._votacion_ids.add(vid)

    def expand_votacion(self, compact: dict, chamber: str) -> dict:
        """Convert a compact votacion back to the expanded format
        used by generate_site.py."""
        votes = []
        for v in compact.get("v", []):
            ni, bi, pi, vc = v
            name = self.names[ni] if ni < len(self.names) else ""
            bloc = self.blocs[bi] if bi < len(self.blocs) else ""
            province = self.provinces[pi] if pi < len(self.provinces) else ""
            vote_str = VOTE_DECODE.get(vc, "")
            entry = {
                "name": name,
                "bloc": bloc,
                "province": province,
                "vote": vote_str,
                "coalition": classify_bloc(bloc),
            }
            photo_id = self.photo_ids.get(str(ni), "")
            if photo_id:
                entry["photo_id"] = photo_id
            votes.append(entry)

        # compute URL for source page if possible
        url = ""
        if chamber == "diputados" and compact.get("id"):
            slug = compact.get("sl", "")
            if not slug:
                # Fallback for records saved before the slug field was added
                slug = _get_slug_map().get(str(compact.get("id")), "")
            if slug:
                url = f"{HCDN_BASE}/votacion/{slug}/{compact.get('id')}"
            else:
                url = f"{HCDN_BASE}/votacion/{compact.get('id')}"
        elif chamber == "senadores" and compact.get("id"):
            url = f"{SENADO_BASE}/votaciones/detalleActa/{compact.get('id')}"

        return {
            "id": compact.get("id", ""),
            "chamber": chamber,
            "url": url,
            "title": compact.get("t", ""),
            "date": compact.get("d", ""),
            "result": compact.get("r", ""),
            "type": compact.get("tp", ""),
            "period": compact.get("p", ""),
            "afirmativo": compact.get("a", 0),
            "negativo": compact.get("n", 0),
            "abstencion": compact.get("b", 0),
            "ausente": compact.get("u", 0),
            "votes": votes,
        }

    def expand_all(self, chamber: str) -> list[dict]:
        """Expand all votaciones to the format used by generate_site.py."""
        return [self.expand_votacion(v, chamber) for v in self.votaciones]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch(url: str, delay: float = REQUEST_DELAY,
          raise_for_status: bool = True) -> requests.Response | None:
    """Fetch a URL with rate limiting and error handling."""
    time.sleep(delay)
    try:
        resp = SESSION.get(url, timeout=30)
        if raise_for_status:
            resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        if not isinstance(e, requests.HTTPError):
            log.warning(f"Failed to fetch {url}: {e}")
        return None


def fetch_soup(url: str, delay: float = REQUEST_DELAY) -> BeautifulSoup | None:
    resp = fetch(url, delay)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "lxml")


# ---------------------------------------------------------------------------
# Photo helpers
# ---------------------------------------------------------------------------

def download_photo(url: str, filename: str) -> bool:
    """Download a photo to docs/fotos/. Returns True on success.
    Skips download if file already exists and has content.
    """
    dest = FOTOS_DIR / filename
    if dest.exists() and dest.stat().st_size > 500:
        return True  # already downloaded
    try:
        time.sleep(0.15)
        resp = SESSION.get(url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 500:
            with open(dest, "wb") as f:
                f.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


# ===========================================================================
#  DIPUTADOS SCRAPER
# ===========================================================================

def _parse_hcdn_page(resp: requests.Response, votacion_id: str, url: str) -> dict | None:
    """Parse an already-fetched HCDN votacion page into a data dict.

    Returns the dict, or None if the page has no voting content.
    """
    soup = BeautifulSoup(resp.text, "lxml")

    if not soup.find(string=re.compile("¿CÓMO VOTÓ?")):
        return None

    result = {
        "id": votacion_id,
        "chamber": "diputados",
        "url": url,
        "title": "",
        "date": "",
        "result": "",
        "period": "",
        "type": "",
        "afirmativo": 0,
        "negativo": 0,
        "abstencion": 0,
        "ausente": 0,
        "votes": [],
    }

    # Title — h4 element, may include date appended
    title_el = soup.find("h4")
    if title_el:
        raw_title = title_el.get_text(strip=True)
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}\s*-?\s*\d{2}:\d{2})", raw_title)
        if date_match:
            result["date"] = date_match.group(1).strip()
            result["title"] = raw_title[:date_match.start()].strip()
        else:
            result["title"] = raw_title

    # Period
    period_el = soup.find("h5", string=re.compile(r"Período"))
    if period_el:
        result["period"] = period_el.get_text(strip=True)

    # Date fallback
    if not result["date"]:
        for h5 in soup.find_all("h5"):
            text = h5.get_text(strip=True)
            dm = re.search(r"\d{2}/\d{2}/\d{4}", text)
            if dm:
                result["date"] = text
                break

    # Overall result (AFIRMATIVO / NEGATIVO)
    result_h3 = soup.find("h3")
    if result_h3:
        result["result"] = result_h3.get_text(strip=True)

    # Vote counts
    for h3, h4 in zip(soup.find_all("h3"), soup.find_all("h4")):
        try:
            count = int(h3.get_text(strip=True))
            label = h4.get_text(strip=True).upper()
            if "AFIRMATIVO" in label:
                result["afirmativo"] = count
            elif "NEGATIVO" in label:
                result["negativo"] = count
            elif "ABSTENCI" in label:
                result["abstencion"] = count
            elif "AUSENTE" in label:
                result["ausente"] = count
        except (ValueError, AttributeError):
            continue

    # Individual votes from the table
    table = soup.find("table")
    if table:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 5:
                photo_id = ""
                photo_link = cells[0].find("a", href=True)
                if photo_link:
                    photo_id = photo_link["href"].rstrip("/").split("/")[-1]
                name     = cells[1].get_text(strip=True)
                bloc     = cells[2].get_text(strip=True)
                province = cells[3].get_text(strip=True)
                vote     = cells[4].get_text(strip=True)
                if name and vote:
                    entry = {
                        "name": name,
                        "bloc": bloc,
                        "province": province,
                        "vote": vote.upper(),
                        "coalition": classify_bloc(bloc),
                    }
                    if photo_id:
                        entry["photo_id"] = photo_id
                    result["votes"].append(entry)

    return result


def scrape_hcdn_votacion(votacion_id: str) -> dict | None:
    """Fetch + parse a single HCDN votacion page (used for Phase 2 / new IDs).

    Resolves slug URLs automatically via the slug map or ajax/expedientes.
    Returns the data dict or None if the vote doesn't exist / has no data.
    """
    url = HCDN_SLUG_OVERRIDES.get(votacion_id, f"{HCDN_BASE}/votacion/{votacion_id}")
    resp = fetch(url, delay=REQUEST_DELAY, raise_for_status=False)
    if resp is None or resp.status_code != 200:
        if resp is not None and resp.status_code == 417:
            return None  # Genuinely absent
        if votacion_id not in HCDN_SLUG_OVERRIDES:
            slug_url = _find_slug_url(votacion_id)
            if slug_url:
                resp = fetch(slug_url, delay=REQUEST_DELAY, raise_for_status=False)
                if resp is None or resp.status_code != 200:
                    return None
                url = slug_url
            else:
                return None
        else:
            return None
    return _parse_hcdn_page(resp, votacion_id, url)


def scrape_diputados():
    """Scrape all Diputados votaciones.

    Builds a complete id→slug map from the HCDN year-based search pages (all
    years 1993–present), then iterates only the IDs the site actually knows
    about.  IDs already in the local DB are skipped without any HTTP request.
    The correct URL (slug-prefixed or bare) is taken directly from the map.
    """
    log.info("=" * 60)
    log.info("SCRAPING DIPUTADOS")
    log.info("=" * 60)

    db = ConsolidatedDB(DATA_DIR / "diputados.json")
    db.load()
    log.info(f"Existing DB: {len(db.votaciones)} votaciones, "
             f"{len(db.names)} names")

    # Build the slug map once (≈8 s, cached for the rest of the run)
    slug_map = _get_slug_map()

    new_count = 0
    checked   = 0

    log.info(f"Iterating {len(slug_map)} known IDs from slug map")
    for vid_int in sorted(int(k) for k in slug_map):
        vid = str(vid_int)

        # Already have it locally — no HTTP needed
        if db.has_votacion(vid):
            continue

        checked += 1

        # Build URL directly from the map; no probe request required
        slug = slug_map[vid]
        if slug:
            url = f"{HCDN_BASE}/votacion/{slug}/{vid}"
        else:
            url = f"{HCDN_BASE}/votacion/{vid}"

        resp = fetch(url, delay=REQUEST_DELAY, raise_for_status=False)
        if resp is None or resp.status_code != 200:
            continue

        data = _parse_hcdn_page(resp, vid, url)
        if data and data.get("votes"):
            db.add_votacion(data)
            new_count += 1
            if new_count % 50 == 0:
                db.save()
                log.info(f"  Checkpoint: saved {new_count} new (ID {vid})")
            log.info(f"  [{vid}] {data.get('title','')[:80]}")

        if checked % 200 == 0:
            log.info(f"  Progress: checked {checked}, saved {new_count}")

    db.save()
    log.info(f"Diputados: scraped {new_count} new votaciones "
             f"(checked {checked} IDs, total in DB: {len(db.votaciones)})")


# ===========================================================================
#  SENADO SCRAPER
# ===========================================================================

def scrape_senado_actas_list(year: int, existing_ids: set[str]) -> list[dict]:
    """Scrape the list of actas from the Senado for a given year.
    
    The Senado site requires a POST request with the form data
    busqueda_actas[anio]=YEAR to filter by period.
    """
    log.info(f"=== Scraping Senado actas list for {year} ===")

    url = f"{SENADO_BASE}/votaciones/actas"
    actas = []

    # The site uses a form POST to filter by year, not URL parameters
    form_data = {"busqueda_actas[anio]": str(year)}
    
    time.sleep(REQUEST_DELAY)
    try:
        resp = SESSION.post(url, data=form_data, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Failed to fetch Senado actas for {year}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    detail_links = soup.find_all(
        "a", href=re.compile(r"/votaciones/detalleActa/(\d+)")
    )

    for link in detail_links:
        match = re.search(r"/votaciones/detalleActa/(\d+)", link["href"])
        if match:
            acta_id = match.group(1)
            if acta_id not in existing_ids:
                actas.append({
                    "id": acta_id,
                    "text": link.get_text(strip=True),
                })

    log.info(f"Found {len(actas)} new Senado actas for {year}")
    return actas


def scrape_senado_votacion(acta_id: str) -> dict | None:
    """Scrape a single Senado votacion detail page."""
    url = f"{SENADO_BASE}/votaciones/detalleActa/{acta_id}"
    soup = fetch_soup(url, delay=0.5)
    if soup is None:
        return None

    result = {
        "id": acta_id,
        "chamber": "senadores",
        "url": url,
        "title": "",
        "date": "",
        "result": "",
        "type": "",
        "afirmativo": 0,
        "negativo": 0,
        "abstencion": 0,
        "ausente": 0,
        "votes": [],
    }

    content = soup.find(
        "div", class_=re.compile("content|main|votacion", re.I)
    )
    if not content:
        content = soup

    # Title: find <p> immediately after "Acta Nro:" <p>
    acta_nro_p = content.find("p", string=re.compile(r"Acta Nro", re.I))
    if acta_nro_p:
        for sib in acta_nro_p.find_next_siblings():
            if sib.name == "p":
                t = sib.get_text(strip=True)
                if t and "Secretaría" not in t and "Honorable" not in t:
                    result["title"] = t[:300]
                    break

    # Fallback: keyword search
    if not result["title"]:
        for text_node in content.find_all(string=True):
            text = text_node.strip()
            if len(text) > 20 and any(kw in text.lower() for kw in
                    ["ley", "proyecto", "pliego", "acuerdo", "modificación",
                     "régimen", "designación", "modernización"]):
                result["title"] = text[:300]
                break

    if not result["title"]:
        for tag in ["h2", "h3", "h1"]:
            el = content.find(tag)
            if el and len(el.get_text(strip=True)) > 10:
                result["title"] = el.get_text(strip=True)
                break

    # Date
    date_match = re.search(
        r"(\d{2}/\d{2}/\d{4})\s*-?\s*(\d{2}:\d{2})?",
        content.get_text()
    )
    if date_match:
        result["date"] = date_match.group(0).strip()

    # Result
    for text in content.find_all(
        string=re.compile(r"AFIRMATIVO|NEGATIVO", re.I)
    ):
        result["result"] = text.strip()
        break

    # Type
    for text in content.find_all(
        string=re.compile(r"EN GENERAL|EN PARTICULAR", re.I)
    ):
        result["type"] = text.strip()
        break

    # Vote counts
    count_headers = content.find_all("h3")
    count_labels = content.find_all("h4")
    for h3, h4 in zip(count_headers, count_labels):
        try:
            count = int(h3.get_text(strip=True))
            label = h4.get_text(strip=True).upper()
            if "AFIRMATIVO" in label:
                result["afirmativo"] = count
            elif "NEGATIVO" in label:
                result["negativo"] = count
            elif "ABSTENCI" in label:
                result["abstencion"] = count
            elif "AUSENTE" in label:
                result["ausente"] = count
        except (ValueError, AttributeError):
            continue

    # Individual votes from the table
    table = content.find("table")
    if table:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 5:
                name = cells[1].get_text(strip=True)
                bloc = cells[2].get_text(strip=True)
                province = cells[3].get_text(strip=True)
                vote = cells[4].get_text(strip=True)

                name = re.sub(r"^Foto de.*?Nacional\s*", "", name).strip()

                if name and vote:
                    result["votes"].append({
                        "name": name,
                        "bloc": bloc,
                        "province": province,
                        "vote": vote.upper(),
                        "coalition": classify_bloc(bloc),
                    })

    return result


def scrape_senadores():
    """Scrape all new Senado votaciones."""
    log.info("=" * 60)
    log.info("SCRAPING SENADORES")
    log.info("=" * 60)

    db = ConsolidatedDB(DATA_DIR / "senadores.json")
    db.load()
    existing_ids = db._votacion_ids.copy()
    log.info(f"Existing DB: {len(db.votaciones)} votaciones")

    new_count = 0
    for year in SENADO_YEARS:
        actas = scrape_senado_actas_list(year, existing_ids)

        for acta in actas:
            aid = acta["id"]
            if db.has_votacion(aid):
                log.info(f"  Skipping senado votacion {aid} (already exists)")
                continue

            log.info(f"  Scraping senado votacion {aid}...")
            data = scrape_senado_votacion(aid)
            if data and data.get("votes"):
                db.add_votacion(data)
                new_count += 1
                log.info(f"    Saved: {data.get('title', 'Unknown')[:80]}")
            else:
                log.warning(f"    No vote data for senado votacion {aid}")

    db.save()
    log.info(f"Senadores: scraped {new_count} new votaciones "
             f"(total in DB: {len(db.votaciones)})")


# ===========================================================================
#  PHOTO SCRAPERS
# ===========================================================================

def scrape_diputados_photos():
    """Download diputado photos using photo_ids from the consolidated DB."""
    log.info("=" * 60)
    log.info("DOWNLOADING DIPUTADOS PHOTOS")
    log.info("=" * 60)

    db = ConsolidatedDB(DATA_DIR / "diputados.json")
    db.load()

    if not db.photo_ids:
        log.warning("No photo_ids found in diputados database")
        return

    name_to_file: dict[str, str] = {}
    downloaded = 0
    skipped = 0

    for ni_str, photo_id in db.photo_ids.items():
        ni = int(ni_str)
        if ni >= len(db.names):
            continue
        name = db.names[ni]

        url = f"{HCDN_BASE}/assets/diputados/{photo_id}"
        filename = f"dip_{photo_id}.jpg"
        dest = FOTOS_DIR / filename

        if dest.exists() and dest.stat().st_size > 500:
            skipped += 1
            name_to_file[name] = filename
        elif download_photo(url, filename):
            downloaded += 1
            name_to_file[name] = filename

    log.info(f"Diputado photos: {downloaded} new, {skipped} already existed")

    save_json(DATA_DIR / "diputados_photos.json", name_to_file)
    log.info(f"Saved diputados photo mapping ({len(name_to_file)} entries)")


def scrape_senadores_photos():
    """Download senator photos from the Senado open data JSON API."""
    log.info("=" * 60)
    log.info("DOWNLOADING SENADORES PHOTOS")
    log.info("=" * 60)

    # The open-data JSON endpoint provides a list of senators, but the
    # FOTO field is often empty or unreliable.  Instead construct the image
    # URL using the known pattern "fsenaG/<id>.gif" which is what the site
    # actually serves for each senator.
    url = f"{SENADO_BASE}/micrositios/DatosAbiertos/ExportarListadoSenadores/json"
    resp = fetch(url, delay=0.5)
    if resp is None:
        log.warning("Could not fetch Senado open data JSON")
        return

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        log.warning("Invalid JSON from Senado open data")
        return

    rows = data.get("table", {}).get("rows", [])
    log.info(f"Found {len(rows)} senators in open data")

    name_to_file: dict[str, str] = {}
    downloaded = 0
    skipped = 0

    for row in rows:
        sen_id = row.get("ID", "")
        apellido = row.get("APELLIDO", "").strip()
        nombre = row.get("NOMBRE", "").strip()

        if not sen_id:
            continue

        # build URL using fsenaG pattern
        foto_url = f"{SENADO_BASE}/bundles/senadosenadores/images/fsenaG/{sen_id}.gif"

        full_name = f"{apellido}, {nombre}".strip()
        filename = f"sen_{sen_id}.gif"
        dest = FOTOS_DIR / filename

        if dest.exists() and dest.stat().st_size > 500:
            skipped += 1
            name_to_file[full_name] = filename
        elif download_photo(foto_url, filename):
            downloaded += 1
            name_to_file[full_name] = filename

    log.info(f"Senator photos: {downloaded} new, {skipped} already existed")
    save_json(DATA_DIR / "senadores_photos.json", name_to_file)
    log.info(f"Saved senadores photo mapping ({len(name_to_file)} entries)")


# ===========================================================================
#  WIKIPEDIA / WIKIDATA PHOTO FALLBACK
# ===========================================================================

WIKI_ES_API = "https://es.wikipedia.org/w/api.php"
WIKI_EN_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Thumb size for Wikipedia photos (pixels on longest side)
WIKI_THUMB_SIZE = 300


def _name_to_search_query(name: str, chamber: str = "diputado") -> str:
    """Convert 'LASTNAME, Firstname' to a Wikipedia search query.

    Examples:
        'ABAD, Maximiliano' -> 'Maximiliano Abad diputado Argentina'
        'KIRCHNER, Cristina Fernández de' -> 'Cristina Fernández de Kirchner'
    """
    name = name.strip()
    # Remove noise like "Legislador 2", "NO INCORPORADO"
    if "NO INCORPORADO" in name.upper() or "LEGISLADOR" in name.upper():
        return ""

    # Handle "LASTNAME, Firstname" format
    if "," in name:
        parts = name.split(",", 1)
        lastname = parts[0].strip().title()
        firstname = parts[1].strip().title() if len(parts) > 1 else ""
        search_name = f"{firstname} {lastname}".strip()
    else:
        search_name = name.strip().title()

    chamber_term = "diputado" if chamber == "diputados" else "senador"
    return f"{search_name} {chamber_term} Argentina"


def _safe_filename(name: str) -> str:
    """Generate a safe filename from a legislator name."""
    # Normalize unicode, keep only alphanumeric and underscores
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_name).strip("_").lower()
    # Truncate and add a short hash for uniqueness
    if len(safe) > 40:
        safe = safe[:40]
    name_hash = hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
    return f"wiki_{safe}_{name_hash}"


def search_wikipedia_photo(name: str, chamber: str = "diputados") -> str | None:
    """Search Wikipedia for a legislator's photo.

    Strategy:
    1. Search Spanish Wikipedia for the person
    2. Get the page's main image (pageimages API)
    3. If not found, try English Wikipedia
    4. If still not found, try Wikidata image property (P18)

    Returns the thumbnail URL or None.
    """
    query = _name_to_search_query(name, chamber)
    if not query:
        return None

    # --- Try Spanish Wikipedia first ---
    url = search_wikipedia_photo_from_wiki(query, WIKI_ES_API)
    if url:
        return url

    # --- Try English Wikipedia ---
    url = search_wikipedia_photo_from_wiki(query, WIKI_EN_API)
    if url:
        return url

    # --- Try Wikidata as last resort ---
    return search_wikidata_photo(query)


def search_wikipedia_photo_from_wiki(
    query: str, api_base: str
) -> str | None:
    """Search a Wikipedia instance and return the thumbnail URL of the
    best matching article's main image."""
    # Step 1: Search for the article
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": 3,
        "srprop": "snippet",
    }
    try:
        time.sleep(0.2)  # Be respectful to Wikipedia
        resp = SESSION.get(api_base, params=search_params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None

    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    # Check the top results for a page with an image
    for result in results:
        title = result.get("title", "")
        if not title:
            continue

        # Filter: snippet should mention politics/diputado/senador/legislador
        # to avoid false matches (e.g. a football player with same name)
        snippet = result.get("snippet", "").lower()
        # For the first result, accept it even without political keywords
        # For subsequent results, require some political context
        if result != results[0]:
            political_kw = [
                "diputad", "senad", "legislad", "polític", "politic",
                "congres", "cámara", "camara", "bloque", "partido",
                "radical", "peronist", "justiciali", "ucr",
                "libertad avanza", "pro ", "kirchner",
            ]
            if not any(kw in snippet for kw in political_kw):
                continue

        # Step 2: Get pageimages for this article
        img_params = {
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": WIKI_THUMB_SIZE,
        }
        try:
            time.sleep(0.15)
            resp = SESSION.get(api_base, params=img_params, timeout=15)
            resp.raise_for_status()
            img_data = resp.json()
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            continue

        pages = img_data.get("query", {}).get("pages", {})
        for page_id, page_info in pages.items():
            thumb = page_info.get("thumbnail", {})
            source = thumb.get("source", "")
            if source:
                return source

    return None


def search_wikidata_photo(query: str) -> str | None:
    """Search Wikidata for a person and return their P18 (image) property
    as a Wikimedia Commons thumbnail URL."""
    # Search Wikidata for the entity
    search_params = {
        "action": "wbsearchentities",
        "search": query.replace(" diputado Argentina", "").replace(
            " senador Argentina", ""
        ),
        "language": "es",
        "format": "json",
        "limit": 3,
        "type": "item",
    }
    try:
        time.sleep(0.2)
        resp = SESSION.get(WIKIDATA_API, params=search_params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None

    entities = data.get("search", [])
    for entity in entities:
        entity_id = entity.get("id", "")
        if not entity_id:
            continue

        # Fetch the entity's P18 (image) claim
        claims_params = {
            "action": "wbgetclaims",
            "entity": entity_id,
            "property": "P18",
            "format": "json",
        }
        try:
            time.sleep(0.15)
            resp = SESSION.get(
                WIKIDATA_API, params=claims_params, timeout=15
            )
            resp.raise_for_status()
            claims_data = resp.json()
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            continue

        claims = claims_data.get("claims", {}).get("P18", [])
        if not claims:
            continue

        # Get the image filename from the first claim
        try:
            image_name = (
                claims[0]["mainsnak"]["datavalue"]["value"]
            )
        except (KeyError, IndexError):
            continue

        if image_name:
            # Convert Commons filename to a thumbnail URL
            safe_name = image_name.replace(" ", "_")
            # Use Wikimedia Commons thumb API
            md5 = hashlib.md5(safe_name.encode("utf-8")).hexdigest()
            encoded_name = quote(safe_name)
            thumb_url = (
                f"https://upload.wikimedia.org/wikipedia/commons/thumb/"
                f"{md5[0]}/{md5[:2]}/{encoded_name}/"
                f"{WIKI_THUMB_SIZE}px-{encoded_name}"
            )
            # Commons may serve .jpg for .svg etc, try adding .jpg suffix
            # for non-raster formats
            if safe_name.lower().endswith(".svg"):
                thumb_url += ".jpg"
            return thumb_url

    return None


def _collect_names_missing_photos(
    chamber: str,
) -> list[str]:
    """Get list of legislator names that don't have photos yet."""
    if chamber == "diputados":
        db_path = DATA_DIR / "diputados.json"
        photos_path = DATA_DIR / "diputados_photos.json"
    else:
        db_path = DATA_DIR / "senadores.json"
        photos_path = DATA_DIR / "senadores_photos.json"

    if not db_path.exists():
        return []

    db = ConsolidatedDB(db_path)
    db.load()
    all_names = set(db.names)

    # Load existing photo mappings
    existing_photos: set[str] = set()
    if photos_path.exists():
        try:
            with open(photos_path, "r", encoding="utf-8") as f:
                existing_photos = set(json.load(f).keys())
        except (json.JSONDecodeError, OSError):
            pass

    # previous versions loaded wiki photos for fallback, but we no longer
    # use that source so skip this step.

    # Filter out names that already have photos and noise entries
    missing = []
    for name in sorted(all_names):
        if name in existing_photos:
            continue
        # Skip noise entries
        upper = name.upper()
        if "NO INCORPORADO" in upper or "LEGISLADOR" in upper:
            continue
        if len(name) < 4:
            continue
        missing.append(name)

    return missing



# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [DATA_DIR, FOTOS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


# ===========================================================================
#  MAIN
# ===========================================================================

def main():
    ensure_dirs()

    log.info("Como Voto - Data Scraper v2 (consolidated JSON)")
    log.info(f"Data directory: {DATA_DIR}")

    # Parse CLI args
    # Usage: python scraper.py [diputados] [senadores] [fotos]
    # Default: all three
    args = [a.lower() for a in sys.argv[1:]] \
        if len(sys.argv) > 1 else ["diputados", "senadores", "fotos"]

    if "diputados" in args:
        scrape_diputados()

    if "senadores" in args:
        scrape_senadores()

    if "fotos" in args:
        scrape_diputados_photos()
        scrape_senadores_photos()

    log.info("Scraping complete!")


if __name__ == "__main__":
    main()

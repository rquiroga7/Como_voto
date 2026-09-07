from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FOTOS_DIR = BASE_DIR / "docs" / "fotos"

HCDN_BASE = "https://votaciones.hcdn.gob.ar"
SENADO_BASE = "https://www.senado.gob.ar"

# Rate-limiting: seconds between requests. Override with COMO_VOTO_DELAY
# env var (e.g. 2 for slow local runs to avoid rate throttling/IP blocking).
REQUEST_DELAY = float(os.environ.get("COMO_VOTO_DELAY", "0.3"))
# Jitter factor (0-1): adds up to delay*jitter extra random seconds per request.
JITTER_FACTOR = float(os.environ.get("COMO_VOTO_JITTER", "0.25"))
SECTION_DIVIDER = "=" * 60
# Daily runs should only scrape votaciones; photos are heavy and
# should be triggered explicitly (e.g. bi-monthly workflow).
# See runner.py:11 and .github/workflows/update-data.yml:5
DEFAULT_RUN_TARGETS = ("diputados", "senadores")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scraper")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "ComoVoto-Scraper/2.0 (https://github.com/rquiroga7/Como_voto; educational project)",
        "Accept-Language": "es-AR,es;q=0.9",
    }
)


PJ_KEYWORDS = [
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

PRO_KEYWORDS = [
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


def log_section(title: str) -> None:
    log.info(SECTION_DIVIDER)
    log.info(title)
    log.info(SECTION_DIVIDER)


def parse_vote_counts(container) -> dict[str, int]:
    """Parse h3/h4 vote counters used by both chamber pages."""
    counts = {
        "afirmativo": 0,
        "negativo": 0,
        "abstencion": 0,
        "ausente": 0,
    }
    for h3, h4 in zip(container.find_all("h3"), container.find_all("h4")):
        try:
            count = int(h3.get_text(strip=True))
            label = h4.get_text(strip=True).upper()
            if "AFIRMATIVO" in label:
                counts["afirmativo"] = count
            elif "NEGATIVO" in label:
                counts["negativo"] = count
            elif "ABSTENCI" in label:
                counts["abstencion"] = count
            elif "AUSENTE" in label:
                counts["ausente"] = count
        except (ValueError, AttributeError):
            continue
    return counts


def build_vote_entry(
    name: str,
    bloc: str,
    province: str,
    vote: str,
    photo_id: str = "",
) -> dict | None:
    """Create a normalized vote row in the canonical output shape."""
    name = name.strip()
    vote = vote.strip()
    if not name or not vote:
        return None

    entry = {
        "name": name,
        "bloc": bloc,
        "province": province,
        "vote": vote.upper(),
        "coalition": classify_bloc(bloc),
    }
    if photo_id:
        entry["photo_id"] = photo_id
    return entry


def extract_votes_from_table(
    table,
    *,
    include_photo_id: bool = False,
    name_cleaner: Callable[[str], str] | None = None,
) -> list[dict]:
    """Extract vote rows from chamber tables with optional name cleanup."""
    clean_name = name_cleaner or (lambda value: value)
    votes: list[dict] = []

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        photo_id = ""
        if include_photo_id:
            photo_link = cells[0].find("a", href=True)
            if photo_link:
                photo_id = photo_link["href"].rstrip("/").split("/")[-1]

        entry = build_vote_entry(
            name=clean_name(cells[1].get_text(strip=True)),
            bloc=cells[2].get_text(strip=True),
            province=cells[3].get_text(strip=True),
            vote=cells[4].get_text(strip=True),
            photo_id=photo_id,
        )
        if entry:
            votes.append(entry)

    return votes


def clean_senado_name(name: str) -> str:
    return re.sub(r"^Foto de.*?Nacional\s*", "", name).strip()


def build_hcdn_votacion_url(votacion_id: str, slug: str = "") -> str:
    """Build a stable HCDN votacion URL for bare or slug-prefixed IDs."""
    if slug:
        return f"{HCDN_BASE}/votacion/{slug}/{votacion_id}"
    return f"{HCDN_BASE}/votacion/{votacion_id}"


def polite_sleep(delay: float = REQUEST_DELAY) -> None:
    """Sleep `delay` seconds plus random jitter to avoid rate-limiting."""
    time.sleep(delay + random.uniform(0, delay * JITTER_FACTOR))


def fetch(
    url: str,
    delay: float = REQUEST_DELAY,
    raise_for_status: bool = True,
) -> requests.Response | None:
    """Fetch a URL with rate limiting and error handling."""
    polite_sleep(delay)
    try:
        resp = SESSION.get(url, timeout=30)
        if raise_for_status:
            resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        if not isinstance(exc, requests.HTTPError):
            log.warning(f"Failed to fetch {url}: {exc}")
        return None


def fetch_soup(url: str, delay: float = REQUEST_DELAY) -> BeautifulSoup | None:
    resp = fetch(url, delay)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "lxml")


def download_photo(url: str, filename: str) -> bool:
    """Download a photo to docs/fotos/. Returns True on success.
    Skips download if file already exists and has content.
    """
    dest = FOTOS_DIR / filename
    if dest.exists() and dest.stat().st_size > 500:
        return True
    try:
        time.sleep(0.15)
        resp = SESSION.get(url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 500:
            with open(dest, "wb") as handle:
                handle.write(resp.content)
            return True
    except requests.RequestException:
        pass
    return False


def ensure_dirs() -> None:
    """Create data directories if they don't exist."""
    for directory in [DATA_DIR, FOTOS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))

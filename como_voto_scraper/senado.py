from __future__ import annotations

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .core import (
    DATA_DIR,
    REQUEST_DELAY,
    SENADO_BASE,
    SESSION,
    clean_senado_name,
    extract_votes_from_table,
    fetch_soup,
    log,
    log_section,
    parse_vote_counts,
)
from .db import ConsolidatedDB

# Available on website: 2005 onwards (earlier years have no digital records)
SENADO_YEARS = list(range(2005, datetime.now().year + 1))


def scrape_senado_actas_list(year: int, existing_ids: set[str]) -> list[dict]:
    """Scrape the list of actas from the Senado for a given year."""
    log.info(f"=== Scraping Senado actas list for {year} ===")

    url = f"{SENADO_BASE}/votaciones/actas"
    actas = []
    form_data = {"busqueda_actas[anio]": str(year)}

    time.sleep(REQUEST_DELAY)
    try:
        resp = SESSION.post(url, data=form_data, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning(f"Failed to fetch Senado actas for {year}: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    detail_links = soup.find_all("a", href=re.compile(r"/votaciones/detalleActa/(\d+)"))

    for link in detail_links:
        match = re.search(r"/votaciones/detalleActa/(\d+)", link["href"])
        if not match:
            continue

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

    content = soup.find("div", class_=re.compile("content|main|votacion", re.I))
    if not content:
        content = soup

    acta_nro_p = content.find("p", string=re.compile(r"Acta Nro", re.I))
    if acta_nro_p:
        for sibling in acta_nro_p.find_next_siblings():
            if sibling.name != "p":
                continue

            text = sibling.get_text(strip=True)
            if text and "Secretaría" not in text and "Honorable" not in text:
                result["title"] = text[:300]
                break

    if not result["title"]:
        for text_node in content.find_all(string=True):
            text = text_node.strip()
            if len(text) > 20 and any(
                keyword in text.lower()
                for keyword in [
                    "ley",
                    "proyecto",
                    "pliego",
                    "acuerdo",
                    "modificación",
                    "régimen",
                    "designación",
                    "modernización",
                ]
            ):
                result["title"] = text[:300]
                break

    if not result["title"]:
        for tag in ["h2", "h3", "h1"]:
            element = content.find(tag)
            if element and len(element.get_text(strip=True)) > 10:
                result["title"] = element.get_text(strip=True)
                break

    date_match = re.search(r"(\d{2}/\d{2}/\d{4})\s*-?\s*(\d{2}:\d{2})?", content.get_text())
    if date_match:
        result["date"] = date_match.group(0).strip()

    for text in content.find_all(string=re.compile(r"AFIRMATIVO|NEGATIVO", re.I)):
        result["result"] = text.strip()
        break

    for text in content.find_all(string=re.compile(r"EN GENERAL|EN PARTICULAR", re.I)):
        result["type"] = text.strip()
        break

    result.update(parse_vote_counts(content))

    table = content.find("table")
    if table:
        result["votes"] = extract_votes_from_table(
            table,
            name_cleaner=clean_senado_name,
        )

    return result


def scrape_senadores() -> None:
    """Scrape all new Senado votaciones."""
    log_section("SCRAPING SENADORES")

    db = ConsolidatedDB(DATA_DIR / "senadores.json")
    db.load()
    existing_ids = db._votacion_ids.copy()
    log.info(f"Existing DB: {len(db.votaciones)} votaciones")

    new_count = 0
    for year in SENADO_YEARS:
        actas = scrape_senado_actas_list(year, existing_ids)
        for acta in actas:
            acta_id = acta["id"]
            if db.has_votacion(acta_id):
                log.info(f"  Skipping senado votacion {acta_id} (already exists)")
                continue

            log.info(f"  Scraping senado votacion {acta_id}...")
            data = scrape_senado_votacion(acta_id)
            if data and data.get("votes"):
                db.add_votacion(data)
                new_count += 1
                log.info(f"    Saved: {data.get('title', 'Unknown')[:80]}")
            else:
                log.warning(f"    No vote data for senado votacion {acta_id}")

    if new_count > 0:
        db.save()
        log.info(
            "Senadores: scraped %s new votaciones (total in DB: %s)"
            % (new_count, len(db.votaciones))
        )
    else:
        log.info(
            "Senadores: no new votaciones (total in DB: %s)"
            % (len(db.votaciones))
        )

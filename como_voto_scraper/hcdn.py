from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .core import (
    DATA_DIR,
    HCDN_BASE,
    REQUEST_DELAY,
    SESSION,
    build_hcdn_votacion_url,
    extract_votes_from_table,
    fetch,
    log,
    log_section,
    parse_vote_counts,
    polite_sleep,
)
from .db import ConsolidatedDB

# Some HCDN IDs return 500 from the plain /votacion/{id} URL but work with a
# slug prefix. Map id -> full URL path (slug + id) for those cases.
HCDN_SLUG_OVERRIDES: dict[str, str] = {
    "393": f"{HCDN_BASE}/votacion/derecho-identidad-genero-general/393",
    "394": f"{HCDN_BASE}/votacion/derecho-identidad-genero-articulo-5/394",
    "395": f"{HCDN_BASE}/votacion/derecho-identidad-genero-articulo-11/395",
}

_SLUG_STOP_WORDS = {
    "a",
    "al",
    "de",
    "del",
    "la",
    "las",
    "el",
    "los",
    "en",
    "con",
    "por",
    "sobre",
    "para",
    "y",
    "o",
    "e",
    "que",
    "se",
    "un",
    "una",
    "unos",
    "unas",
    "su",
    "sus",
    "lo",
    "le",
    "les",
    "nos",
}

# Cache for the id->slug map built from HCDN year-based search pages.
_SLUG_MAP: dict[str, str] | None = None
SLUG_MAP_CACHE_FILE = DATA_DIR / "hcdn_slug_map.json"


def _slugify(text: str, max_words: int = 4) -> str:
    """Convert a Spanish law title into an HCDN-style URL slug."""
    text = text.split(":")[0]
    text = (
        unicodedata.normalize("NFKD", text.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [
        word
        for word in text.split()
        if word and word not in _SLUG_STOP_WORDS and len(word) > 1
    ]
    return "-".join(words[:max_words])


def fetch_hcdn_slug_map(update_latest_only: bool = False) -> dict[str, str]:
    """Scrape /votaciones/search for every year to build a complete id->slug map.
    
    If update_latest_only is True, only fetch the current year and merge with cache.

    NOTE (2026-07-30 change): HCDN now requires grecaptcha `rtk` token
    for /votaciones/search and returns a shell HTML with 0 `redirectActa`
    rows.  We detect this (0 rows + no DataTable) and keep the cached
    map, letting the tail-scan fallback discover new IDs instead.
    """
    slug_map: dict[str, str] = {}
    current_year = datetime.now().year
    
    # If updating only latest year, load existing cache first
    if update_latest_only and SLUG_MAP_CACHE_FILE.exists():
        try:
            import json
            with open(SLUG_MAP_CACHE_FILE, "r", encoding="utf-8") as f:
                slug_map = json.load(f)
            log.info(f"Loaded {len(slug_map)} existing slug entries from cache")
        except Exception as exc:
            log.warning(f"Failed to load slug cache: {exc}")
    
    # Determine which years to scrape
    if update_latest_only and slug_map:
        years_to_scrape = [current_year]
        log.info(f"Updating slug map for year {current_year} only...")
    else:
        years_to_scrape = list(range(1993, current_year + 1))
        log.info(f"Building full slug map for years 1993-{current_year}...")
    
    for year in years_to_scrape:
        try:
            resp = SESSION.post(
                f"{HCDN_BASE}/votaciones/search",
                data={"txtSearch": "", "anoSearch": str(year)},
                timeout=20,
            )
            if resp.status_code == 403:
                log.warning(f"  Slug map: {year} got 403 — site may be down/rate-limited, keeping cache")
                continue
            matches = re.findall(r"redirectActa\((\d+),(\d+),'([^']*)'\)", resp.text)
            for votacion_id, _, slug in matches:
                slug_map[votacion_id] = slug
            log.info(f"  Slug map: {year}: {len(matches)} rows")
            if not matches and "recaptcha" in resp.text.lower() and "grecaptcha" in resp.text.lower():
                log.warning(f"  Slug map: {year} returned recaptcha shell (site now requires rtk token) — search is broken, will use tail scan")
        except Exception as exc:
            log.warning(f"  Slug map: {year} failed: {exc}")
        polite_sleep()

    with_slug = sum(1 for slug in slug_map.values() if slug)
    log.info(
        f"Slug map ready: {len(slug_map)} IDs total, {with_slug} require slug URLs"
    )
    return slug_map


def _is_hcdn_available() -> bool:
    """Lightweight health check to avoid brute-forcing when HCDN is down.

    Returns False if HCDN returns 403/timeout, in which case callers
    should abort without iterating over votaciones to avoid IP blocking.
    """
    try:
        resp = SESSION.get(HCDN_BASE, timeout=8)
        if resp.status_code == 403:
            log.warning("HCDN health check: 403 Forbidden — site is blocking, aborting scrape to avoid IP ban")
            return False
        # Any 2xx/3xx is considered available; even 5xx is not a block
        return resp.status_code < 500
    except requests.RequestException as exc:
        log.warning(f"HCDN health check failed: {exc} — aborting scrape to avoid brute-force on down site")
        return False


def get_slug_map() -> dict[str, str]:
    """Return the cached id->slug map, building it on the first call."""
    global _SLUG_MAP
    if _SLUG_MAP is None:
        # Try to load from cache file first
        if SLUG_MAP_CACHE_FILE.exists():
            try:
                import json
                with open(SLUG_MAP_CACHE_FILE, "r", encoding="utf-8") as f:
                    old_slug_map = json.load(f)
                log.info(f"Loaded slug map from cache: {len(old_slug_map)} entries")
                
                # Update only the latest year
                current_year = datetime.now().year
                log.info(f"Updating slug map for year {current_year}...")
                new_slug_map = fetch_hcdn_slug_map(update_latest_only=True)
                
                # Only save if the map actually changed
                if new_slug_map != old_slug_map:
                    _SLUG_MAP = new_slug_map
                    with open(SLUG_MAP_CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(_SLUG_MAP, f)
                    log.info(f"Saved updated slug map to cache: {SLUG_MAP_CACHE_FILE}")
                else:
                    _SLUG_MAP = old_slug_map
                    log.info("Slug map unchanged — skipping save")
            except Exception as exc:
                log.warning(f"Failed to load slug map cache: {exc}")
                _SLUG_MAP = fetch_hcdn_slug_map(update_latest_only=False)
        else:
            log.info("Building HCDN slug map from search pages (one-time) ...")
            _SLUG_MAP = fetch_hcdn_slug_map(update_latest_only=False)
        
        # Save to cache (first-time build only)
        if not SLUG_MAP_CACHE_FILE.exists():
            try:
                import json
                with open(SLUG_MAP_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(_SLUG_MAP, f)
                log.info(f"Saved slug map to cache: {SLUG_MAP_CACHE_FILE}")
            except Exception as exc:
                log.warning(f"Failed to save slug map cache: {exc}")
    return _SLUG_MAP


def find_slug_url(votacion_id: str) -> str | None:
    """Return the correct slug URL for an HCDN vote ID that returns HTTP 500."""
    slug_map = get_slug_map()

    if votacion_id in slug_map:
        slug = slug_map[votacion_id]
        if slug:
            url = build_hcdn_votacion_url(votacion_id, slug)
            log.info(f"  [{votacion_id}] Slug URL from map: {url}")
            return url
        return None

    log.debug(f"  [{votacion_id}] Not in slug map; trying ajax/expedientes")
    try:
        response = SESSION.post(
            f"{HCDN_BASE}/ajax/expedientes",
            data={"id-acta": votacion_id, "texto": ""},
            timeout=10,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except Exception:
        return None

    if not payload.get("success") or not payload.get("expedientes"):
        return None

    title = payload["expedientes"][0].get("titulo", "")
    if not title:
        return None

    bases = []
    for num_words in (3, 4):
        base = _slugify(title, max_words=num_words)
        if base and base not in bases:
            bases.append(base)

    vote_suffixes = [
        "",
        "general",
        "particular",
        "en-general",
        "en-particular",
    ] + [f"articulo-{number}" for number in range(1, 21)]

    for base in bases:
        for suffix in vote_suffixes:
            slug = f"{base}-{suffix}" if suffix else base
            url = build_hcdn_votacion_url(votacion_id, slug)
            try:
                response = SESSION.get(url, timeout=8)
                if response.status_code == 200 and "¿CÓMO VOTÓ?" in response.text:
                    log.info(f"  [{votacion_id}] Discovered slug URL: {url}")
                    return url
            except Exception:
                pass
            polite_sleep()

    log.warning(f"  [{votacion_id}] Could not find slug URL (title: {title[:60]})")
    return None


def parse_hcdn_page(resp: requests.Response, votacion_id: str, url: str) -> dict | None:
    """Parse an already-fetched HCDN votacion page into a data dict."""
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

    title_el = soup.find("h4")
    if title_el:
        raw_title = title_el.get_text(strip=True)
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}\s*-?\s*\d{2}:\d{2})", raw_title)
        if date_match:
            result["date"] = date_match.group(1).strip()
            result["title"] = raw_title[: date_match.start()].strip()
        else:
            result["title"] = raw_title

    period_el = soup.find("h5", string=re.compile(r"Período"))
    if period_el:
        result["period"] = period_el.get_text(strip=True)

    if not result["date"]:
        for h5 in soup.find_all("h5"):
            text = h5.get_text(strip=True)
            if re.search(r"\d{2}/\d{2}/\d{4}", text):
                result["date"] = text
                break

    result_h3 = soup.find("h3")
    if result_h3:
        result["result"] = result_h3.get_text(strip=True)

    result.update(parse_vote_counts(soup))

    table = soup.find("table")
    if table:
        result["votes"] = extract_votes_from_table(table, include_photo_id=True)

    return result


def scrape_hcdn_votacion(votacion_id: str) -> dict | None:
    """Fetch + parse a single HCDN votacion page."""
    url = HCDN_SLUG_OVERRIDES.get(votacion_id, build_hcdn_votacion_url(votacion_id))
    resp = fetch(url, delay=REQUEST_DELAY, raise_for_status=False)
    if resp is None or resp.status_code != 200:
        if resp is not None and resp.status_code == 417:
            return None
        if votacion_id not in HCDN_SLUG_OVERRIDES:
            slug_url = find_slug_url(votacion_id)
            if slug_url:
                resp = fetch(slug_url, delay=REQUEST_DELAY, raise_for_status=False)
                if resp is None or resp.status_code != 200:
                    return None
                url = slug_url
            else:
                return None
        else:
            return None
    return parse_hcdn_page(resp, votacion_id, url)


def _tail_scan_new_votaciones(
    db: ConsolidatedDB,
    slug_map: dict[str, str],
    max_consecutive_misses: int = 12,
    max_probe: int = 80,
) -> int:
    """Discover votaciones beyond the slug_map without brute-forcing the whole range.

    The HCDN search endpoint (/votaciones/search) now requires a
    grecaptcha `rtk` token (added ~2026-07-30) and returns a shell
    HTML with 0 `redirectActa` rows.  Instead of scanning 1..6000,
    we only probe incrementally after the highest known ID.

    This is O(new_votaciones) not O(all_ids) and avoids the
    expensive `find_slug_url` brute-force over 25 suffixes.

    Returns number of new votaciones saved.
    """
    if not slug_map and not db.votaciones:
        return 0

    try:
        max_slug = max(int(k) for k in slug_map) if slug_map else 0
    except ValueError:
        max_slug = 0
    try:
        max_db = max(int(k) for k in db._votacion_ids) if db._votacion_ids else 0  # type: ignore[attr-defined]
    except ValueError:
        max_db = 0
    start = max(max_slug, max_db) + 1
    # If DB is empty, start from 1 would be brute-force — skip tail scan
    if start <= 1:
        return 0

    log.info(f"Trying incremental tail scan from ID {start} (max_consecutive_misses={max_consecutive_misses}, max_probe={max_probe})...")
    new_count = 0
    consecutive_misses = 0
    consecutive_403 = 0
    probed = 0

    for vid_int in range(start, start + max_probe):
        vid = str(vid_int)
        if db.has_votacion(vid):
            consecutive_misses = 0
            continue

        probed += 1
        # Prefer slug from map if available, otherwise bare URL
        slug = slug_map.get(vid, "")
        url = build_hcdn_votacion_url(vid, slug)
        resp = fetch(url, delay=REQUEST_DELAY, raise_for_status=False)

        if resp is None:
            consecutive_misses += 1
            consecutive_403 = 0
            if consecutive_misses >= max_consecutive_misses:
                log.info(f"  Tail scan: {consecutive_misses} consecutive misses, stopping at ID {vid}")
                break
            continue

        if resp.status_code == 403:
            consecutive_403 += 1
            log.warning(f"  [{vid}] 403 Forbidden (consecutive {consecutive_403}) — site may be rate-limiting or down")
            if consecutive_403 >= 3:
                log.warning("  Tail scan aborted after 3 consecutive 403s")
                break
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                break
            continue

        consecutive_403 = 0

        if resp.status_code == 417:
            # 417 = no such acta (gap) — not an error
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                log.info(f"  Tail scan: {consecutive_misses} consecutive 417 gaps, stopping at ID {vid}")
                break
            continue

        if resp.status_code != 200:
            # 500 may need slug fallback, 404 etc.
            if resp.status_code == 500 and not slug:
                slug_url = find_slug_url(vid)
                if slug_url:
                    resp2 = fetch(slug_url, delay=REQUEST_DELAY, raise_for_status=False)
                    if resp2 is not None and resp2.status_code == 200:
                        data = parse_hcdn_page(resp2, vid, slug_url)
                        if data and data.get("votes"):
                            db.add_votacion(data)
                            new_count += 1
                            consecutive_misses = 0
                            log.info(f"  [{vid}] {data.get('title','')[:80]} (via slug)")
                            # keep slug_map up to date for future runs
                            slug_map[vid] = slug_url.split("/votacion/")[1].split("/")[0] if "/votacion/" in slug_url else ""
                            continue
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                break
            continue

        # 200 — check if it's a real votacion page
        if "¿CÓMO VOTÓ?" not in resp.text:
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                log.info(f"  Tail scan: {consecutive_misses} misses (no vote table), stopping at {vid}")
                break
            continue

        data = parse_hcdn_page(resp, vid, url)
        if data and data.get("votes"):
            db.add_votacion(data)
            new_count += 1
            consecutive_misses = 0
            log.info(f"  [{vid}] {data.get('title','')[:80]}")
            if new_count % 20 == 0:
                db.save()
                log.info(f"  Checkpoint (tail): saved {new_count} new (ID {vid})")
        else:
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                break

    if probed:
        log.info(f"Tail scan probed {probed} IDs, saved {new_count} new")

    # Persist any new slug entries discovered during tail scan
    if new_count and slug_map:
        try:
            import json as _json

            with open(SLUG_MAP_CACHE_FILE, "w", encoding="utf-8") as fh:
                _json.dump(slug_map, fh)
            log.info(f"Updated slug map cache with tail-scan entries: {SLUG_MAP_CACHE_FILE}")
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Failed to save slug map after tail scan: {exc}")

    return new_count


def scrape_diputados() -> None:
    """Scrape all Diputados votaciones."""
    log_section("SCRAPING DIPUTADOS")

    # Early abort if HCDN is down/blocking (403/timeout on health check).
    # This prevents brute-forcing 3054 IDs when site returns 403 as seen
    # 2026-09-01 13:25:20 Read timed out / 403 on votaciones.hcdn.gob.ar.
    if not _is_hcdn_available():
        log.warning("Skipping Diputados scrape — HCDN site unavailable (health check failed)")
        return

    db = ConsolidatedDB(DATA_DIR / "diputados.json")
    db.load()
    log.info(f"Existing DB: {len(db.votaciones)} votaciones, {len(db.names)} names")

    slug_map = get_slug_map()

    new_count = 0
    checked = 0

    # Avoid IP blocking: daily run should not re-try every old gap
    # (e.g. 2109) with 30s timeout each. Only check recent missing IDs
    # + tail scan beyond max. Full backfill can be run manually with
    # `python scraper.py diputados --full` if needed.
    try:
        max_db_id = max(int(k) for k in db._votacion_ids) if db._votacion_ids else 0  # type: ignore[attr-defined]
    except ValueError:
        max_db_id = 0
    # Only consider missing IDs within last 800 IDs or beyond max (tail)
    # This limits daily traffic to ~80-150 fetches instead of 125+ old gaps.
    recent_threshold = max_db_id - 800
    candidate_ids = [
        vid_int
        for vid_int in sorted(int(key) for key in slug_map)
        if not db.has_votacion(str(vid_int)) and vid_int > recent_threshold
    ]
    log.info(
        f"Iterating {len(candidate_ids)} recent missing IDs from slug map (threshold >{recent_threshold}, total map {len(slug_map)})"
    )

    consecutive_timeouts = 0
    consecutive_403 = 0
    for vid_int in candidate_ids:
        vid = str(vid_int)
        # Already filtered, but keep check for safety
        if db.has_votacion(vid):
            continue

        checked += 1
        url = build_hcdn_votacion_url(vid, slug_map[vid])

        resp = fetch(url, delay=REQUEST_DELAY, raise_for_status=False)
        if resp is None:
            consecutive_timeouts += 1
            log.warning(f"  [{vid}] fetch timeout/failure ({consecutive_timeouts}/5 consecutive)")
            if consecutive_timeouts >= 5:
                log.warning("  Too many consecutive timeouts — HCDN site may be down/rate-limited, aborting map iteration early")
                break
            continue
        # Reset timeout counter on any response
        consecutive_timeouts = 0

        if resp.status_code == 403:
            consecutive_403 += 1
            log.warning(f"  [{vid}] 403 Forbidden ({consecutive_403}/3)")
            if consecutive_403 >= 3:
                log.warning("  Aborting map iteration after 3 consecutive 403s")
                break
            continue
        consecutive_403 = 0

        if resp.status_code != 200:
            # 417 = gap, 500 = slug needed etc. — not a timeout, don't count
            continue

        data = parse_hcdn_page(resp, vid, url)
        if data and data.get("votes"):
            db.add_votacion(data)
            new_count += 1
            if new_count % 50 == 0:
                db.save()
                log.info(f"  Checkpoint: saved {new_count} new (ID {vid})")
            log.info(f"  [{vid}] {data.get('title', '')[:80]}")

        if checked % 200 == 0:
            log.info(f"  Progress: checked {checked}, saved {new_count}")

    # Fallback for site changes after 2026-07-30: search now needs
    # grecaptcha rtk token and returns 0 rows.  Probe incrementally
    # beyond max known ID instead of brute-forcing 1..6000.
    tail_new = 0
    if checked == 0 or new_count == 0:
        # Only run tail scan if slug_map iteration found nothing —
        # avoids double work when search still works.
        # Also run if search returned 0 rows for current year (stale map).
        tail_new = _tail_scan_new_votaciones(db, slug_map)
        new_count += tail_new

    if new_count > 0:
        db.save()
        log.info(
            "Diputados: scraped %s new votaciones (checked %s IDs via map + %s via tail, total in DB: %s)"
            % (new_count, checked, tail_new, len(db.votaciones))
        )
    else:
        log.info(
            "Diputados: no new votaciones (checked %s IDs, total in DB: %s)"
            % (checked, len(db.votaciones))
        )

from __future__ import annotations

import sys

from .core import DATA_DIR, DEFAULT_RUN_TARGETS, ensure_dirs, log
from .hcdn import scrape_diputados
from .photos import scrape_diputados_photos, scrape_senadores_photos
from .senado import scrape_senadores


def parse_run_targets(argv: list[str]) -> set[str]:
    """Normalize CLI args into task names, defaulting to the full pipeline."""
    if not argv:
        return set(DEFAULT_RUN_TARGETS)
    return {arg.lower() for arg in argv}


def run_photo_scrapers() -> None:
    scrape_diputados_photos()
    scrape_senadores_photos()


def main() -> None:
    ensure_dirs()

    log.info("Como Voto - Data Scraper v2 (consolidated JSON)")
    log.info(f"Data directory: {DATA_DIR}")

    targets = parse_run_targets(sys.argv[1:])

    # Run each chamber independently so a failure/timeout in one
    # (e.g. HCDN 403/captcha after 2026-07-30) does not block the other.
    # See hcdn.py:86 and update-data.yml:30.
    if "diputados" in targets:
        try:
            scrape_diputados()
        except Exception as exc:  # noqa: BLE001
            log.error(f"Diputados scraper failed (continuing to senadores): {exc}", exc_info=True)

    if "senadores" in targets:
        try:
            scrape_senadores()
        except Exception as exc:  # noqa: BLE001
            log.error(f"Senadores scraper failed: {exc}", exc_info=True)

    if "fotos" in targets:
        try:
            run_photo_scrapers()
        except Exception as exc:  # noqa: BLE001
            log.error(f"Fotos scraper failed: {exc}", exc_info=True)

    log.info("Scraping complete!")

from __future__ import annotations

import json
import re
from pathlib import Path

from .core import HCDN_BASE, SENADO_BASE, classify_bloc, log

# Vote code mapping (compact integer codes for storage)
VOTE_ENCODE = {
    "AFIRMATIVO": 1,
    "NEGATIVO": 2,
    "ABSTENCION": 3,
    "ABSTENCIÓN": 3,   # accented form from Senate HTML
    "AUSENTE": 4,
    "PRESIDENTE": 5,
}
VOTE_DECODE = {value: key for key, value in VOTE_ENCODE.items()}


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
        self.photo_ids: dict[str, str] = {}
        self.votaciones: list[dict] = []
        self._name_idx: dict[str, int] = {}
        self._bloc_idx: dict[str, int] = {}
        self._prov_idx: dict[str, int] = {}
        self._votacion_ids: set[str] = set()

    def load(self) -> None:
        """Load existing data from disk."""
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(f"Error loading {self.path}: {exc}")
            return

        self.names = data.get("names", [])
        self.blocs = data.get("blocs", [])
        self.provinces = data.get("provinces", [])
        self.photo_ids = data.get("photo_ids", {})
        self.votaciones = data.get("votaciones", [])

        self._name_idx = {name: idx for idx, name in enumerate(self.names)}
        self._bloc_idx = {bloc: idx for idx, bloc in enumerate(self.blocs)}
        self._prov_idx = {prov: idx for idx, prov in enumerate(self.provinces)}
        self._votacion_ids = {str(votacion["id"]) for votacion in self.votaciones}

    def save(self) -> None:
        """Save to disk (compact JSON, no indent)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "names": self.names,
            "blocs": self.blocs,
            "provinces": self.provinces,
            "photo_ids": self.photo_ids,
            "votaciones": self.votaciones,
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))

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

    def add_votacion(self, raw: dict) -> None:
        """Add a votacion in the raw (expanded) format, converting to compact."""
        vid = str(raw.get("id", ""))
        if vid in self._votacion_ids:
            return

        compact_votes = []
        for vote_row in raw.get("votes", []):
            name = vote_row.get("name", "").strip()
            if not name:
                continue
            name_idx = self._get_name_idx(name)
            bloc_idx = self._get_bloc_idx(vote_row.get("bloc", ""))
            prov_idx = self._get_prov_idx(vote_row.get("province", ""))
            vote_code = VOTE_ENCODE.get(vote_row.get("vote", "").upper(), 0)
            compact_votes.append([name_idx, bloc_idx, prov_idx, vote_code])

            photo_id = vote_row.get("photo_id", "")
            if photo_id:
                self.photo_ids[str(name_idx)] = photo_id

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

        raw_url = raw.get("url", "")
        slug_match = re.search(r"/votacion/([^/]+)/\d+$", raw_url)
        if slug_match:
            entry["sl"] = slug_match.group(1)

        self.votaciones.append(entry)
        self._votacion_ids.add(vid)

    def expand_votacion(self, compact: dict, chamber: str) -> dict:
        """Convert a compact votacion back to the expanded site format."""
        votes = []
        for vote_data in compact.get("v", []):
            name_idx, bloc_idx, prov_idx, vote_code = vote_data
            name = self.names[name_idx] if name_idx < len(self.names) else ""
            bloc = self.blocs[bloc_idx] if bloc_idx < len(self.blocs) else ""
            province = self.provinces[prov_idx] if prov_idx < len(self.provinces) else ""
            vote_str = VOTE_DECODE.get(vote_code, "")
            entry = {
                "name": name,
                "bloc": bloc,
                "province": province,
                "vote": vote_str,
                "coalition": classify_bloc(bloc),
            }
            photo_id = self.photo_ids.get(str(name_idx), "")
            if photo_id:
                entry["photo_id"] = photo_id
            votes.append(entry)

        url = ""
        if chamber == "diputados" and compact.get("id"):
            slug = compact.get("sl", "")
            if not slug:
                # Local import avoids circular dependency between db and hcdn
                from .hcdn import get_slug_map

                slug = get_slug_map().get(str(compact.get("id")), "")
            votacion_id = str(compact.get("id"))
            if slug:
                url = f"{HCDN_BASE}/votacion/{slug}/{votacion_id}"
            else:
                url = f"{HCDN_BASE}/votacion/{votacion_id}"
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
        return [self.expand_votacion(votacion, chamber) for votacion in self.votaciones]

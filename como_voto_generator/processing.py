from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .data_loading import clean_date, extract_year
from .laws import get_common_name
from .normalization import (
    NAME_ALIASES,
    classify_bloc_mapped,
    normalize_name,
    normalize_province,
    normalize_vote,
)


def compute_majority_vote(votes: list[dict], coalition: str) -> str:
    def _norm(value: str) -> str:
        return (
            unicodedata.normalize("NFKD", value or "")
            .encode("ascii", "ignore")
            .decode("ascii")
            .upper()
        )

    coalition_up = _norm(coalition) if coalition else coalition
    wanted = {coalition_up} if coalition_up else set()
    coalition_votes = []
    for vote_row in votes:
        coal = vote_row.get("coalition") or classify_bloc_mapped(vote_row.get("bloc", ""))
        coal_up = _norm(coal)
        bloc_up = _norm(vote_row.get("bloc", ""))
        if coal_up in wanted or any(item in bloc_up for item in wanted):
            coalition_votes.append(vote_row)
    if not coalition_votes:
        return "N/A"

    counts = defaultdict(int)
    for vote_row in coalition_votes:
        vote = vote_row["vote"].upper()
        if "AFIRMATIV" in vote:
            counts["AFIRMATIVO"] += 1
        elif "NEGATIV" in vote:
            counts["NEGATIVO"] += 1
        elif "ABSTENCI" in vote or "ABSTENCION" in vote:
            counts["ABSTENCION"] += 1
        elif "AUSENT" in vote:
            counts["AUSENTE"] += 1

    active_counts = {key: value for key, value in counts.items() if key != "AUSENTE"}
    if not active_counts:
        return "AUSENTE"

    return max(active_counts, key=active_counts.get)


def compute_combined_majority(votes: list[dict], coalitions: list[str]) -> str:
    """Calcula el voto mayoritario combinando múltiples coaliciones."""

    def _norm(value: str) -> str:
        return (
            unicodedata.normalize("NFKD", value or "")
            .encode("ascii", "ignore")
            .decode("ascii")
            .upper()
        )

    wanted = set(_norm(coalition) for coalition in coalitions)
    coalition_votes = []
    for vote_row in votes:
        coal = vote_row.get("coalition") or classify_bloc_mapped(vote_row.get("bloc", ""))
        coal_up = _norm(coal)
        bloc_up = _norm(vote_row.get("bloc", ""))
        if coal_up in wanted or any(item in bloc_up for item in wanted):
            coalition_votes.append(vote_row)
    if not coalition_votes:
        return "N/A"

    counts = defaultdict(int)
    for vote_row in coalition_votes:
        vote = vote_row["vote"].upper()
        if "AFIRMATIV" in vote:
            counts["AFIRMATIVO"] += 1
        elif "NEGATIV" in vote:
            counts["NEGATIVO"] += 1
        elif "ABSTENCI" in vote or "ABSTENCION" in vote:
            counts["ABSTENCION"] += 1
        elif "AUSENT" in vote:
            counts["AUSENTE"] += 1

    active_counts = {key: value for key, value in counts.items() if key != "AUSENTE"}
    if not active_counts:
        return "AUSENTE"

    return max(active_counts, key=active_counts.get)


def is_contested(year: int | None, pj_majority: str, opp_majority: str) -> bool:
    """Devuelve True cuando una votación está disputada entre PJ y oposición."""
    if year is None:
        return False
    if pj_majority in ("N/A", "AUSENTE"):
        return False
    if opp_majority in ("N/A", "AUSENTE"):
        return False
    return pj_majority != opp_majority


def _article_from_slug(url: str) -> str | None:
    """Extrae una etiqueta de artículo/sección desde un slug de URL de HCDN."""
    match = re.search(r"/votacion/([^/]+)/\d+$", url)
    if not match:
        return None

    slug = match.group(1).lower()

    art = re.search(r"-articulo-(\d+[a-z]*)$", slug)
    if art:
        return f"Art. {art.group(1)}"

    title_match = re.search(r"-titulo-([ivxlcdm\d]+(?:-[a-z]+)?)$", slug)
    if title_match:
        return f"Título {title_match.group(1).upper()}"

    if slug.endswith("-en-particular") or slug.endswith("-particular"):
        return "En Particular"

    return None


def build_legislator_data(all_votaciones: list[dict], law_groups: dict) -> dict:
    legislators = {}

    votacion_to_group = {}
    for group_key, group_data in law_groups.items():
        for votacion in group_data["votaciones"]:
            votacion_key = f"{votacion.get('chamber', '')}_{votacion.get('id', '')}"
            votacion_to_group[votacion_key] = group_key

    for votacion in all_votaciones:
        year = extract_year(votacion.get("date", ""))
        votacion_id = votacion.get("id", "")
        chamber = votacion.get("chamber", "")
        title = votacion.get("title", "")
        date = clean_date(votacion.get("date", ""))
        vtype = votacion.get("type", "")

        votacion_key = f"{chamber}_{votacion_id}"
        group_key = votacion_to_group.get(votacion_key, "")
        group_data = law_groups.get(group_key, {})
        law_display_name = group_data.get("common_name") or group_data.get("title", title)

        # Coalition definitions (case-insensitive matching)
        PJ_COALITIONS = [
            "PJ",
            "JUSTICIALISTAS",
            "FRENTE PARA LA VICTORIA",
            "FRENTE DE TODOS",
            "UNION POR LA PATRIA",
            "UXP",
            "Unidad Ciudadana",
            "Frente Justicialista",
        ]
        UCR_COALITIONS = [
            "UCR",
            "UNION CIVICA RADICAL",
            "UNIÓN CÍVICA RADICAL",
            "RADICAL",
            "CC",
            "ACyS",
            "UDESO",
            "FPCyS",
            "Frente Progresista Cívico y Social",
            "Unión para el Desarrollo Social",
            "Acuerdo Cívico y Social",
            "Concertación para Una Nación Avanzada",
            "UNA",
            "ARI",
            "Argentinos por una República de Iguales",
            "Coalición Cívica",
            "Coalición Cívica ARI",
        ]
        JXC_COALITIONS = [
            "UCR",
            "Unión Cívica Radical",
            "Union Civica Radical",
            "JxC",
            "Juntos por el Cambio",
            "CC",
            "Coalición Cívica",
            "Cambiemos",
            "PRO",
            "Propuesta Republicana",
            "Frente Pro",
            "Frente Cambiemos",
            "Frente Juntos por el Cambio",
            "ARI",
            "Coalición Cívica ARI",
        ]
        LLA_PRO_COALITIONS = [
            "LLA",
            "PRO",
            "Juntos por el Cambio",
            "Alianza La Libertad Avanza",
        ]

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
        if (
            "moción de orden" in title_low
            or "moción del diputado" in title_low
            or "mocion de orden" in title_low
            or "pedido de licencia" in title_low
            or "pedido de pref" in title_low
            or "apartamiento del reglamento solicitado" in title_low
            or "pedido tratamiento sobre tablas" in title_low
        ):
            contested = False
        else:
            contested = is_contested(year, pj_majority, opp_majority)

        for vote_record in votacion.get("votes", []):
            name = vote_record.get("name", "").strip()
            if not name:
                continue

            name_key = normalize_name(name)
            name_key = NAME_ALIASES.get(name_key, name_key)

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
                    "_yr_blocs": {},
                    "_yr_provinces": {},
                    "alignment": {
                        "PJ": {"total": 0, "aligned": 0},
                        "PRO": {"total": 0, "aligned": 0},
                        "LLA": {"total": 0, "aligned": 0},
                        "UCR": {"total": 0, "aligned": 0},
                    },
                    "yearly_alignment": {},
                }

            leg = legislators[name_key]
            if normalize_name(name) == name_key:
                leg["name"] = name
                leg["name_key"] = name_key

            if chamber not in leg["chambers"]:
                leg["chambers"].append(chamber)

            leg["bloc"] = vote_record.get("bloc", leg["bloc"])
            leg["province"] = normalize_province(vote_record.get("province", leg["province"]))
            leg["coalition"] = classify_bloc_mapped(vote_record.get("bloc", leg.get("bloc", "")))
            leg["chamber"] = chamber

            norm_vote = normalize_vote(vote_record.get("vote", ""))

            # Determine article_label - prioritize _is_en_general flag from law group
            article_label = _article_from_slug(votacion.get("url", ""))
            if not article_label:
                # Check if this votacion is marked as En General in the law group
                if votacion.get("_is_en_general"):
                    article_label = "En General"
                else:
                    title_upper = title.upper()
                    title_match = re.search(r"T[IÍ]TULO\s+([\dIVXLCDM]+)", title_upper)
                    if title_match:
                        article_label = f"Título {title_match.group(1)}"
                    elif "EN GENERAL" in title_upper or vtype.upper() == "EN GENERAL":
                        article_label = "En General"
                    elif "EN PARTICULAR" in title_upper or vtype.upper() == "EN PARTICULAR":
                        art_match = re.search(r"ART[IÍ]?CULO?\s*\.?\s*(\d+)", title, re.IGNORECASE)
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
                "pro": combined_jxc,
                "lla": combined_lla_pro,
                "ucr": combined_ucr,
                "tp": vtype,
                "gk": group_key,
                "ln": law_display_name[:120] if law_display_name else "",
                "cn": group_data.get("common_name", ""),
                "al": article_label,
                "eg": bool(votacion.get("_is_en_general")),
            }
            vot_url = votacion.get("url")
            if vot_url:
                vote_entry["url"] = vot_url
            leg["votes"].append(vote_entry)

            if year:
                yr_key = str(year)
                if yr_key not in leg["yearly_stats"]:
                    leg["yearly_stats"][yr_key] = {
                        "AFIRMATIVO": 0,
                        "NEGATIVO": 0,
                        "ABSTENCION": 0,
                        "AUSENTE": 0,
                        "PRESIDENTE": 0,
                        "total": 0,
                    }
                leg["yearly_stats"][yr_key][norm_vote] = leg["yearly_stats"][yr_key].get(norm_vote, 0) + 1
                leg["yearly_stats"][yr_key]["total"] += 1

                # Track bloc counts per (chamber, year) for term computation
                bloc_val = vote_record.get("bloc", "").strip()
                if bloc_val:
                    yr_blocs = leg["_yr_blocs"]
                    if chamber not in yr_blocs:
                        yr_blocs[chamber] = {}
                    if yr_key not in yr_blocs[chamber]:
                        yr_blocs[chamber][yr_key] = {}
                    yr_blocs[chamber][yr_key][bloc_val] = yr_blocs[chamber][yr_key].get(bloc_val, 0) + 1

                # Track province counts per (chamber, year) for term computation
                prov_val = normalize_province(vote_record.get("province", "").strip())
                if prov_val:
                    yr_provs = leg["_yr_provinces"]
                    if chamber not in yr_provs:
                        yr_provs[chamber] = {}
                    if yr_key not in yr_provs[chamber]:
                        yr_provs[chamber][yr_key] = {}
                    yr_provs[chamber][yr_key][prov_val] = yr_provs[chamber][yr_key].get(prov_val, 0) + 1

                if yr_key not in leg["yearly_alignment"]:
                    leg["yearly_alignment"][yr_key] = {
                        "PJ": {"total": 0, "aligned": 0},
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
                    if combined_jxc not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["PRO"]["total"] += 1
                        if norm_vote == combined_jxc:
                            leg["yearly_alignment"][yr_key]["PRO"]["aligned"] += 1
                        if year is not None and 2015 <= year <= 2023:
                            leg["alignment"]["PRO"]["total"] += 1
                            if norm_vote == combined_jxc:
                                leg["alignment"]["PRO"]["aligned"] += 1

                    # LLA + PRO combined majority (tracked under LLA field too)
                    if combined_lla_pro not in ("N/A", "AUSENTE"):
                        leg["yearly_alignment"][yr_key]["LLA"]["total"] += 1
                        if norm_vote == combined_lla_pro:
                            leg["yearly_alignment"][yr_key]["LLA"]["aligned"] += 1
                        if year is not None and year >= 2024:
                            leg["alignment"]["LLA"]["total"] += 1
                            if norm_vote == combined_lla_pro:
                                leg["alignment"]["LLA"]["aligned"] += 1

    return legislators

#!/usr/bin/env python3
"""
Build the bloc → coalition mapping.

Reads all unique bloc names from the diputados and senadores consolidated
databases and classifies each into one of: PJ, PRO, LLA, OTROS.

Classification is based on:
- Wikipedia party/alliance data (https://es.wikipedia.org/wiki/Anexo:Partidos_políticos_de_Argentina)
- Elección legislativa results
- Historical coalition memberships
- Manual overrides for provincial parties and edge cases

Output: data/bloc_coalition_map.json
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ============================================================================
# Manual overrides: exact lowercase bloc name → coalition
# These take absolute priority over keyword matching.
# Sources: Wikipedia party pages, elecciones legislativas results.
# ============================================================================
MANUAL_OVERRIDES: dict[str, str] = {
    # ---- Empty / undefined ----
    "": "OTROS",
    "bloque sin definir": "OTROS",
    "no integra bloque": "OTROS",
    "sin especificar": "OTROS",
    "test1": "OTROS",

    # ---- Peronismo Federal / dissidents → NOT mainstream PJ ----
    # These are PJ splinters that ran their own tickets or broke with K/FdT.
    # Wikipedia: "Peronismo Federal" is its own political space.
    "peronismo federal": "OTROS",
    "peronista federal": "OTROS",
    "frente peronista federal": "OTROS",
    "corriente peronista federal": "OTROS",
    "corriente de pensamiento federal": "OTROS",
    "unión celeste y blanca": "OTROS",
    "unión celeste y blanco": "OTROS",
    "justicialismo republicano": "OTROS",
    "peronista salteño": "OTROS",
    "encuentro republicano federal": "OTROS",  # Pichetto post-K
    "dignidad peronista": "OTROS",  # small dissident bloc
    "dignidad y justicia": "OTROS",

    # ---- PJ-allied provincial parties ----
    # Wikipedia: Frente Cívico por Santiago consistently allied with PJ nationally.
    "frente cívico por santiago": "PJ",
    "frente civico por santiago": "PJ",
    # Wikipedia: FCyS de Catamarca → allied with PJ (Corpacci, Jalil)
    "frente cívico y social de catamarca": "PJ",
    "fte. cívico y social de catamarca": "PJ",
    "frente cívico y social": "PJ",
    "frente cívico social": "PJ",
    # Wikipedia: Frente Renovador de la Concordia (Misiones) → PJ-allied
    "frente de la concordia misionero": "PJ",
    "fte. renov. de la conc. misiones - fpv-pj": "PJ",
    # Regional PJ factions
    "chubut somos todos": "PJ",
    "concertación entrerriana": "PJ",
    "unión por córdoba": "PJ",
    "unión por entre ríos": "PJ",  # Bordet (PJ)
    "concertación forja": "PJ",  # Radicalismo K
    "unión por san juan": "OTROS",  # mixed, independent
    "unión por todos": "OTROS",
    "unión por argentina": "OTROS",

    # Senadores: PJ-allied
    "frente popular": "PJ",
    "misiones": "PJ",  # Misiones senators → PJ-allied
    "movere por santa cruz": "PJ",
    "tucuman": "PJ",  # Tucumán → PJ historically
    "unidad federal": "PJ",  # PJ Senate bloc
    "lealtad y dignidad justicialista": "PJ",
    "partido de la victoria": "PJ",

    # ---- Provincial independent parties → OTROS ----
    # Wikipedia: MPN → "Regionalismo neuquino Neoperonismo", independent
    "movimiento popular neuquino": "OTROS",
    "movimiento popular  neuquino": "OTROS",  # double space variant
    # Wikipedia: MPF → "Regionalismo fuegino Atrapalotodo"
    "movimiento popular fueguino": "OTROS",
    # Wikipedia: MPJ → "Federalismo Regionalismo jujeño", varies (allied with LLA 2023)
    "movimiento popular jujeño": "OTROS",
    # Wikipedia: JSRN → "Regionalismo rionegrino Atrapalotodo"
    "juntos somos rio negro": "OTROS",
    "juntos somos río negro": "OTROS",
    "juntos somos rÍo negro": "OTROS",
    # Wikipedia: Bloquista → "Regionalismo sanjuanino Populismo"
    "bloquista de san juan": "OTROS",
    "partido bloquista de san juan": "OTROS",
    # Wikipedia: Cruzada Renovadora → "Regionalismo sanjuanino Federalismo"
    "cruzada renovadora": "OTROS",
    # Wikipedia: Partido Liberal de Corrientes → historically UCR/PRO-allied
    "liberal de corrientes": "PRO",
    "partido liberal de corrientes": "PRO",
    # Wikipedia: Fuerza Republicana → "Bussismo Neofascismo" (Tucumán, independent)
    "fuerza republicana": "OTROS",
    "autonomista de corrientes": "OTROS",
    "somos fueguinos": "OTROS",

    # ---- PRO precursors & allies ----
    # Wikipedia: Compromiso para el Cambio → Macri's party before PRO
    "compromiso para el cambio": "PRO",
    # Wikipedia: Recrear → merged into PRO in 2009
    "recrear": "PRO",
    "recrear p\\ crecimiento": "PRO",
    "recrear para el crecimiento": "PRO",
    "recrear -- tucumán": "PRO",
    # Wikipedia: Ricardo Balbín → UCR faction
    "ricardo balbin": "PRO",
    # SUMA + UNEN → center-right anti-K coalition (UCR+CC+GEN+PS)
    "suma + unen": "PRO",
    # Alianza → UCR+FREPASO 1997-2001 → anti-PJ
    "alianza": "PRO",
    # Buenos Aires por el Cambio → PRO variant
    "buenos aires por el cambio": "PRO",
    # Movimiento Nacional Alfonsinista → UCR
    "movimiento nacional alfonsinista": "PRO",
    # Diálogo por Buenos Aires → PRO-allied
    "diálogo por buenos aires": "PRO",
    # Frente Progresista Cívico y Social (Santa Fe, Binner) → OTROS (progressive)
    "frente prog. civico y social": "OTROS",
    "frente progresista cívico y social": "OTROS",
    "frente producción y trabajo": "OTROS",
    "frente produccion y trabajo": "OTROS",
    "frente proyecto corrientes": "OTROS",  # provincial
    "frente partido nuevo": "OTROS",

    # ---- LLA and allies ----
    # Wikipedia: Avanza Libertad → Espert, allied with LLA
    "avanza libertad": "LLA",
    # Fuerzas del Cielo
    "fuerzas del cielo - espacio liberal f.c.e": "LLA",
    # Futuro y Libertad
    "futuro y libertad": "LLA",

    # ---- Federal / centrist → OTROS ----
    "compromiso federal": "OTROS",
    "consenso federal": "OTROS",
    "federal": "OTROS",
    "acción federal": "OTROS",
    "acción por la república": "OTROS",  # Cavallo
    "encuentro federal": "OTROS",
    "frente cívico - córdoba": "OTROS",  # separate from Sgo del Estero
    "frente cívico tucumán": "OTROS",
    "gen": "OTROS",  # Stolbizer
    "hacemos coalicion federal": "OTROS",  # Schiaretti
    "innovacion federal": "OTROS",
    "la neuquinidad": "OTROS",
    "pais federal": "OTROS",
    "la argentina de los valores": "OTROS",

    # ---- PJ small/associated blocs ----
    "bg juan b. bustos": "PJ",  # Córdoba PJ governor
    "frente justicia unión y libertad": "PJ",  # FREJULI, PJ alliance
    "frente por la inclusión social": "PJ",  # K-aligned
    "frente del movimiento popular": "PJ",  # PJ-aligned
    "por santa cruz": "PJ",  # K stronghold
    "partido por la justicia social": "PJ",  # PJ
    "frente para el cambio": "PJ",  # K-allied in Chaco
    "unidad bonaerense": "PJ",  # PJ Buenos Aires
    "solidaridad e igualdad (si)": "PJ",  # Bonasso, K-aligned
    "solidaridad e igualdad (si) - ari (t.d.f": "PJ",
    "solidaridad e igualdad (si) - proyecto p": "PJ",
    "solidario si": "PJ",
    "p.a.i.s.": "PJ",  # Menemist PJ
    "emancipación y justicia": "PJ",  # K-aligned
    "frepaso": "OTROS",  # Pre-2003 coalition, not PJ proper

    # ---- Small/other parties → OTROS ----
    "frente norte": "OTROS",
    "frente de unidad provincial": "OTROS",
    "sobera\u00eda popular": "OTROS",
    "soberania popular": "OTROS",
    "primero argentina": "OTROS",
    "democracia igualitaria y participativa": "OTROS",
    "desarrollo y justicia": "OTROS",
    "diálogo y trabajo": "OTROS",
    "coherencia": "OTROS",
    "convergencia": "OTROS",
    "convergencia federal": "OTROS",
    "cordoba federal": "OTROS",
    "córdoba trabajo y producción": "OTROS",
    "de la concertación": "OTROS",
    "defendamos cordoba": "OTROS",
    "defendamos santa fe": "OTROS",
    "nuevo espacio entrerriano": "OTROS",
    "nuevo espacio santafesino": "OTROS",
    "santa fe federal": "OTROS",
    "santa fe en movimiento": "OTROS",
    "nuevo encuentro por la democracia y la equidad": "PJ",
    "encuentro popular y social": "PJ",
    "encuentro popular": "PJ",
    "encuentro": "OTROS",
    "somos": "OTROS",
    "somos mendoza": "OTROS",
    "somos san juan": "OTROS",
    "todos juntos por san juan": "OTROS",
    "salta somos todos": "OTROS",
    "elijo catamarca": "OTROS",
    "primero tucumán": "OTROS",
    "primero san luis": "OTROS",
    "avanzar san luis": "OTROS",
    "la union mendocina": "OTROS",
    "adelante buenos aires": "OTROS",
    "buenos aires": "OTROS",
    "buenos aires libre": "OTROS",

    # ---- Left parties → OTROS ----
    "partido socialista": "OTROS",
    "partido socialista popular": "OTROS",
    "socialista": "OTROS",
    "partido comunista": "OTROS",
    "bloque de los trabajadores": "OTROS",
    "proyecto sur": "OTROS",
    "movimiento proyecto sur": "OTROS",
    "libres del sur": "OTROS",
    "izquierda unida": "OTROS",
    "partido intransigente": "OTROS",

    # ---- Senadores specific ----
    "cambio federal": "OTROS",
    "concertación plural": "OTROS",
    "convicción federal": "OTROS",
    "despierta chubut": "OTROS",
    "esperanza federal": "OTROS",
    "federalismo santafesino": "OTROS",
    "federalismo y liberación": "OTROS",
    "frente civico de la provincia de cordoba": "OTROS",
    "frente cívico jujeño": "OTROS",
    "hay futuro argentina": "OTROS",
    "independencia": "OTROS",
    "justicia social federal": "OTROS",
    "movimiento neuquino": "OTROS",
    "pares": "OTROS",
    "peronismo republicano rio negro": "OTROS",
    "primero los salteños": "OTROS",
    "producción y trabajo": "OTROS",
    "provincias unidas": "OTROS",
    "proyecto buenos aires federal": "OTROS",
    "proyecto sur-unen": "OTROS",
    "puntano independiente": "OTROS",
    "radical independiente": "PRO",
    "radical rionegrino": "PRO",
    "rio - frente progresista": "OTROS",
    "trabajo y dignidad": "OTROS",
    "vecinalista - partido nuevo": "OTROS",
    "alianza coalición cívica": "PRO",
    "frente pro": "PRO",
    "pro y unión por entre ríos": "PRO",
    "ucr - unión cívica radical": "PRO",
    "la libertad avanza": "LLA",

    # Frente Renovador de la Concordia Social (Senado Misiones)
    "frente renovador de la concordia social": "PJ",
    "frente nacional y popular": "PJ",
    "frente para la victoria - pj": "PJ",
    "frente de todos": "PJ",
    "frente cÍvico por santiago": "PJ",
    "frente cÍvico y social de catamarca": "PJ",
    "justicialista": "PJ",
    "justicialista 8 de octubre": "PJ",
    "justicialista para el dialogo de los argentinos": "PJ",
    "justicialista san luis": "PJ",
    "nuevo encuentro": "PJ",
    "partido justicialista la pampa": "PJ",
    "pj frente para la victoria": "PJ",
    "unidad ciudadana": "PJ",
    "partido renovador de salta": "OTROS",
}

# ============================================================================
# Keyword-based auto-classification (fallback when no manual override)
# ============================================================================

_LLA_KW = [
    "la libertad avanza", "libertad avanza",
    "fuerzas del cielo",
    "avanza libertad",
]

_OTROS_OVERRIDE_PHRASES = [
    "peronismo federal",
    "peronista federal",
    "frente peronista federal",
    "corriente peronista federal",
    "unión celeste y blanc",
    "union celeste y blanc",
    "justicialismo republicano",
    "encuentro republicano federal",
]

_PJ_KW = [
    "justicialista",
    "frente de todos",
    "frente para la victoria",
    "unión por la patria", "union por la patria",
    "frente renovador",
    "peronismo", "peronista",
    "frente cívico por santiago", "frente civico por santiago",
    "pj ",
    "unidad ciudadana",
    "frente nacional y popular",
    "frente grande",
    "nuevo encuentro",
    "movimiento evita",
    "eva perón", "eva peron",
    "frente de la concordia",
    "frente cívico y social", "frente civico y social",
    "del bicentenario",
    "partido de la victoria",
    "unión por córdoba", "union por cordoba",
    "concertación entrerriana", "concertacion entrerriana",
    "frente popular",
    "unión por entre ríos", "union por entre rios",
    "chubut somos todos",
    "kolina",
    "patria grande",
]

_PRO_KW = [
    "propuesta republicana",
    "union pro", "unión pro",
    "cambiemos",
    "juntos por el cambio",
    "ucr",
    "unión cívica radical", "union civica radical",
    "coalición cívica", "coalicion civica",
    "evolución radical", "evolucion radical",
    "democracia para siempre",
    "a.r.i",
    "compromiso para el cambio",
    "recrear",
    "alianza coalición cívica",
]

_PRO_WORD_RE = re.compile(r"\bpro\b")


def classify_bloc_auto(bloc_name: str) -> str:
    """Auto-classify a bloc name using keyword matching."""
    name = bloc_name.lower().strip()
    if not name:
        return "OTROS"

    for kw in _LLA_KW:
        if kw in name:
            return "LLA"

    for phrase in _OTROS_OVERRIDE_PHRASES:
        if phrase in name:
            return "OTROS"

    for kw in _PJ_KW:
        if kw in name:
            return "PJ"

    if _PRO_WORD_RE.search(name):
        return "PRO"
    for kw in _PRO_KW:
        if kw in name:
            return "PRO"

    return "OTROS"


def build_mapping() -> dict[str, str]:
    """Build the complete bloc → coalition mapping."""
    all_blocs: set[str] = set()

    for chamber_file in ["diputados.json", "senadores.json"]:
        path = DATA_DIR / chamber_file
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for bloc in data.get("blocs", []):
                all_blocs.add(bloc)

    mapping: dict[str, str] = {}
    for bloc in sorted(all_blocs):
        key = bloc.lower().strip()
        if key in MANUAL_OVERRIDES:
            coalition = MANUAL_OVERRIDES[key]
        else:
            coalition = classify_bloc_auto(bloc)
        mapping[key] = coalition

    return mapping


def main():
    mapping = build_mapping()

    output_path = DATA_DIR / "bloc_coalition_map.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Saved mapping with {len(mapping)} entries to {output_path}")

    counts: dict[str, int] = {}
    for coalition in mapping.values():
        counts[coalition] = counts.get(coalition, 0) + 1
    print("\nSummary:")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v} blocs")

    print("\n=== Full Mapping ===")
    for bloc, coal in sorted(mapping.items()):
        print(f"  [{coal:5s}] {bloc}")


if __name__ == "__main__":
    main()

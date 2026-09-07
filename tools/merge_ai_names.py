"""Merge AI-generated law names (curated by the assistant harness) into the caches."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from como_voto_generator.ai_names import (
    cache_key,
    load_ai_cache,
    load_ai_keywords_cache,
    save_ai_cache,
    save_ai_keywords_cache,
)

# Keyed by first votacion id of each pending group (from pending_titles.json).
NAMES: dict[str, dict] = {
    "3613": {"name": "Disminución de Retribuciones a Letrados", "keywords": ["retribuciones letrados", "auxiliar de justicia", "procesos judiciales", "disminucion salarial"]},
    "3559": {"name": "Insistencia Moratoria Previsional Autónomos", "keywords": ["moratoria previsional", "trabajadores autonomos", "decreto 2104/93", "insistencia veto"]},
    "1952": {"name": "Pliego Embajador Alessandro", "keywords": ["acuerdo embajador", "alessandro", "designacion embajador"]},
    "1953": {"name": "Pliego Embajador Roma", "keywords": ["acuerdo embajador", "roma", "designacion embajador"]},
    "1964": {"name": "Régimen Regulatorio del Gas Licuado", "keywords": ["gas licuado de petroleo", "glp", "falco", "regulacion"]},
    "1906": {"name": "Acuerdo Juez García Wenk", "keywords": ["acuerdo juez", "tribunal oral criminal federal", "formosa", "garcia wenk"]},
    "2319": {"name": "Modificación Ley de Defensa del Consumidor", "keywords": ["defensa del consumidor", "ley 24240", "codigo aeronautico", "guinle", "tasa de justicia"]},
    "2364": {"name": "Reconocimiento de la Lengua de Señas", "keywords": ["lengua de señas argentina", "lsa", "reconocimiento oficial"]},
    "1804": {"name": "Misión MINUSTAH en Haití", "keywords": ["minustah", "haiti", "mision de estabilizacion", "fuerzas armadas"]},
    "2111": {"name": "Protección de Deudores Hipotecarios", "keywords": ["deudores hipotecarios", "leyes 25561", "procedimiento especial"]},
    "1398": {"name": "Acuerdo Juez Molinari", "keywords": ["acuerdo juez", "santiago del estero", "molinari"]},
    "1450": {"name": "Acuerdo Vocal Márquez", "keywords": ["acuerdo vocal", "camara contencioso administrativo", "marquez"]},
    "1075": {"name": "Designación Presidenta Banco Central", "keywords": ["banco central", "marco del pont", "presidenta bcra"]},
    "1092": {"name": "Dictamen de Minoría O.D. 600", "keywords": ["dictamen de minoria", "od 600/2010"]},
    "1066": {"name": "Declaración Quebrada de Conconta", "keywords": ["quebrada de conconta", "san juan", "bien de interes historico", "gioja"]},
    "1006": {"name": "Acuerdo Vocal Cañal", "keywords": ["acuerdo vocal", "camara del trabajo", "canal"]},
    "927": {"name": "Dictamen de Minoría O.D. 603", "keywords": ["dictamen de minoria", "od 603/2010"]},
    "397": {"name": "Ley de Muerte Digna", "keywords": ["muerte digna", "ley 26529", "derechos del paciente", "testamento vital"]},
    "788": {"name": "Acuerdo Procuradora Gils Carbó", "keywords": ["procuradora general", "gils carbo", "acuerdo designacion"]},
    "839": {"name": "Lugar Histórico Punta de los Llanos", "keywords": ["punta de los llanos", "monsenor angelelli", "lugar historico", "la rioja"]},
    "291": {"name": "Rechazo a Denuncia contra Clarín", "keywords": ["grupo clarin", "denuncia penal", "rechazo", "libertad de expresion"]},
    "2713": {"name": "Acuerdo Conjueces Comodoro Rivadavia", "keywords": ["conjueces", "comodoro rivadavia", "camara federal"]},
    "672": {"name": "Acuerdo Vocal Garrigós", "keywords": ["acuerdo vocal", "camara casacion", "garrigos"]},
    "673": {"name": "Acuerdo Fiscal General Gonella", "keywords": ["fiscal general", "gonella", "formosa"]},
    "676": {"name": "Acuerdo Fiscal General Schaefer", "keywords": ["fiscal general", "schaefer", "corrientes"]},
    "677": {"name": "Acuerdo Juez Lauria", "keywords": ["acuerdo juez", "santa fe", "lauria"]},
    "733": {"name": "Acuerdo Presidente Banco Central Fabrega", "keywords": ["banco central", "fabrega", "presidente bcra"]},
    "739": {"name": "Acuerdo Director Banco Central Feldman", "keywords": ["banco central", "feldman", "director bcra"]},
    "744": {"name": "Acuerdo Conjueces Casación Penal", "keywords": ["conjueces", "casacion penal", "camara federal"]},
    "740": {"name": "Acuerdo Director Banco Central Barbier", "keywords": ["banco central", "barbier", "director bcra"]},
    "518": {"name": "Acuerdo Conjueces Corte Suprema", "keywords": ["conjueces", "corte suprema", "designacion"]},
    "557": {"name": "Acuerdo Conjueces Paraná", "keywords": ["conjueces", "parana", "camara federal"]},
    "576": {"name": "Acuerdo Fiscal General Boquín", "keywords": ["fiscal general", "boquin", "camara comercial"]},
    "577": {"name": "Acuerdo Fiscal General Parenti", "keywords": ["fiscal general", "parenti", "san martin"]},
    "579": {"name": "Acuerdo Fiscal Domínguez", "keywords": ["fiscal", "dominguez", "juzgados del trabajo"]},
    "580": {"name": "Acuerdo Fiscal General Córdoba", "keywords": ["fiscal general", "cordoba", "neuquen"]},
    "582": {"name": "Acuerdo Fiscal General Reynares Solari", "keywords": ["fiscal general", "reynares solari", "rosario"]},
    "581": {"name": "Acuerdo Fiscal General Amad", "keywords": ["fiscal general", "amad", "posadas"]},
    "583": {"name": "Acuerdo Fiscal General García Lois", "keywords": ["fiscal general", "garcia lois", "tierra del fuego"]},
    "584": {"name": "Acuerdo Fiscal Investigaciones Administrativas", "keywords": ["fiscal nacional", "investigaciones administrativas", "rodriguez"]},
    "578": {"name": "Acuerdo Fiscal General Palazzani", "keywords": ["fiscal general", "palazzani", "capital federal"]},
    "588": {"name": "Acuerdo Presidente Banco Central Vanoli", "keywords": ["banco central", "vanoli", "presidente bcra"]},
    "589": {"name": "Acuerdo Director Banco Central Biscay", "keywords": ["banco central", "biscay", "director bcra"]},
    "445": {"name": "Acuerdo Síndica Banco Central López", "keywords": ["sindica adjunta", "banco central", "lopez"]},
    "449": {"name": "Acuerdo Juez Kreplak", "keywords": ["acuerdo juez", "kreplak", "la plata"]},
    "451": {"name": "Acuerdo Conjueces Contencioso Administrativo", "keywords": ["conjueces", "gilardi madariaga", "marra gimenez"]},
    "485": {"name": "Acuerdo Defensor Público Bonnin", "keywords": ["defensor publico", "bonnin", "tucuman"]},
    "495": {"name": "Acuerdo Juez Machado Pelloni", "keywords": ["acuerdo juez", "machado pelloni", "tribunal oral"]},
    "5": {"name": "Estatuto del Actor", "keywords": ["actores", "actividad actoral", "estatuto", "teatro"]},
    "22": {"name": "Acuerdo Juez Corte Suprema Rosatti", "keywords": ["corte suprema", "rosatti", "designacion juez"]},
    "21": {"name": "Acuerdo Juez Corte Suprema Rosenkrantz", "keywords": ["corte suprema", "rosenkrantz", "designacion juez"]},
    "52": {"name": "Acuerdo Vocal Robiglio", "keywords": ["acuerdo vocal", "penal economico", "robiglio"]},
    "85": {"name": "Acuerdo Juez Greca", "keywords": ["acuerdo juez", "greca", "general roca"]},
    "136": {"name": "Acuerdo Presidente Banco Central Sturzenegger", "keywords": ["banco central", "sturzenegger", "presidente bcra"]},
    "233": {"name": "Acuerdo Juez Castro", "keywords": ["acuerdo juez", "castro", "tribunal oral"]},
    "234": {"name": "Retiro de Pliego Fiscal Iud", "keywords": ["retiro pliego", "alan iud", "fiscal general"]},
    "3828": {"name": "Ley de Donación de Alimentos", "keywords": ["donacion de alimentos", "vencimiento inminente", "cadenas comerciales", "desperdicio"]},
    "373": {"name": "Acuerdo Conjueces Seguridad Social", "keywords": ["conjueces", "camara seguridad social"]},
    "374": {"name": "Acuerdo Fiscal Martínez", "keywords": ["fiscal", "martinez", "bahia blanca"]},
    "401": {"name": "Acuerdo Juez Argibay", "keywords": ["acuerdo juez", "argibay", "santiago del estero"]},
    "402": {"name": "Acuerdo Juez Fresneda", "keywords": ["acuerdo juez", "fresneda", "paso de los libres"]},
    "2373": {"name": "Acuerdo Embajador Scioli", "keywords": ["embajador", "scioli", "designacion"]},
    "2415": {"name": "Acuerdo Vocal Figuerora", "keywords": ["acuerdo vocal", "figuerora", "casacion penal"]},
    "2551": {"name": "Pliego Embajador Bunge Saravia", "keywords": ["embajador", "bunge saravia", "designacion"]},
    "2550": {"name": "Pliego Embajador Oxenford", "keywords": ["embajador", "oxenford", "designacion"]},
    "2686": {"name": "Pliego Embajadora Crexell", "keywords": ["embajadora", "crexell", "canada"]},
    "2765": {"name": "Acuerdo Jueza Sosa", "keywords": ["acuerdo jueza", "sosa", "la plata"]},
    "2767": {"name": "Acuerdo Juez Emilio Rosatti", "keywords": ["acuerdo juez", "rosatti", "santa fe"]},
    "2769": {"name": "Acuerdo Jueza Michelli", "keywords": ["acuerdo jueza", "michelli", "la plata"]},
    "5945": {"name": "Apartamiento de Reglamento Estévez", "keywords": ["apartamiento de reglamento", "estevez"]},
    "5946": {"name": "Apartamiento de Reglamento Bregman", "keywords": ["apartamiento de reglamento", "bregman"]},
    "5948": {"name": "Protocolo de Enmienda con Francia", "keywords": ["convenio francia", "protocolo de enmienda", "cooperacion"]},
    "5950": {"name": "Acuerdo de Roma sobre Pesca Ilegal", "keywords": ["pesca ilegal", "estado rector del puerto", "acuerdo de roma", "pesca"]},
    "5951": {"name": "Convenio de Seguridad Social con Suiza", "keywords": ["seguridad social", "suiza", "convenio bilateral"]},
    "5952": {"name": "Convenio Seguridad Social San Marino", "keywords": ["seguridad social", "san marino", "convenio bilateral"]},
    "5955": {"name": "Conciliación con Acreedores Bainbridge", "keywords": ["bainbridge", "attestor", "conciliacion", "ciadi"]},
    "2792": {"name": "Acuerdo Vocal Cosentino", "keywords": ["acuerdo vocal", "cosentino", "camara comercial"]},
    "5966": {"name": "Apartamiento de Reglamento Juliano", "keywords": ["apartamiento de reglamento", "juliano", "martinez"]},
    "5967": {"name": "Apartamiento de Reglamento Marino", "keywords": ["apartamiento de reglamento", "marino"]},
    "5968": {"name": "Apartamiento de Reglamento Michel", "keywords": ["apartamiento de reglamento", "michel"]},
    "5969": {"name": "Apartamiento de Reglamento Campo", "keywords": ["apartamiento de reglamento", "campo"]},
    "5970": {"name": "Apartamiento de Reglamento Massot", "keywords": ["apartamiento de reglamento", "massot"]},
    "5971": {"name": "Reforma Carta Orgánica del BCRA", "keywords": ["carta organica", "bcra", "banco central", "reforma"]},
    "5974": {"name": "Modificación Declaración Jurada de Ganancias", "keywords": ["declaracion jurada", "impuesto a las ganancias", "ley 11683", "ley 27799", "simplificacion"]},
    "5975": {"name": "Moción Solicitada por la Sra. RODRIGUEZ MACHADO", "keywords": ["mocion", "rodriguez machado"]},
    "5980": {"name": "Acuerdo Libre Comercio MERCOSUR-Singapur", "keywords": ["mercosur", "singapur", "libre comercio", "acuerdo comercial"]},
    "5981": {"name": "Tratado de Cooperación en Patentes", "keywords": ["patentes", "tratado", "cooperacion", "washington"]},
    "5982": {"name": "Reducción IVA Fécula de Mandioca", "keywords": ["fecula de mandioca", "iva", "ley 23349", "reduccion alicuota"]},
    "5983": {"name": "Declaración Capital Nacional del Teatro", "keywords": ["capital nacional del teatro", "caba", "teatro"]},
    "5984": {"name": "Declaración Capital Nacional del Coleccionismo", "keywords": ["chivilcoy", "coleccionismo", "capital nacional"]},
    "5985": {"name": "Declaración Capital Nacional de la Educación", "keywords": ["san juan", "sarmiento", "capital de la educacion"]},
    "5986": {"name": "Declaración Capital Nacional de la Natación", "keywords": ["santa cruz", "natacion aguas frias", "capital nacional"]},
    "5987": {"name": "Declaración Capital Nacional del Ecoturismo", "keywords": ["tucuman", "ecoturismo", "capital nacional"]},
    "5988": {"name": "Declaración Capital Nacional del Cerdo Negro", "keywords": ["cerdo negro", "cerrillos", "salta"]},
    "5989": {"name": "Declaración Capital Nacional Producción Bubalina", "keywords": ["caa cati", "bubalina", "corrientes", "bubalinos"]},
    "5990": {"name": "Declaración Capital Simbólica 9 de Julio", "keywords": ["san miguel de tucuman", "capital simbolica", "9 de julio", "independencia"]},
    "5991": {"name": "Reorganización Cámara Federal de Tucumán", "keywords": ["camara federal", "tucuman", "reorganizacion", "justicia federal"]},
    "5992": {"name": "Creación Sala II Mar del Plata", "keywords": ["camara federal", "mar del plata", "sala ii", "creacion"]},
    "5994": {"name": "Declaración Patrimonio Camino de Brochero", "keywords": ["camino de brochero", "patrimonio inmaterial", "brochero", "cordoba"]},
    "5995": {"name": "Ley Joaquín", "keywords": ["ley joaquin", "seguridad en el deporte", "actividades recreativas"]},
    "2802": {"name": "Acuerdo Vocal Bertuzzi", "keywords": ["acuerdo vocal", "bertuzzi", "camara criminal correccional"]},
}

# Extra variant keys: adding AI names changes build_law_groups grouping
# (COMMON keys), which can change group titles and thus base cache keys.
EXTRA_KEYS: dict[str, dict] = {
    "disminucion general de las retribuciones de letrados y auxiliar de justicia en los procesos judiciales - articulo 4": {"name": "Disminución de Retribuciones a Letrados", "keywords": ["retribuciones letrados", "auxiliar de justicia", "procesos judiciales", "disminucion salarial"]},
    "o.d. 211 - carta organica del bcra. modificacion. dict. de may. titulo ii": {"name": "Reforma Carta Orgánica del BCRA", "keywords": ["carta organica", "bcra", "banco central", "reforma"]},
    "o.d. 209 - leyes 11.683 y 27.799 relativas a la mod. simpl. de decl. jurada del imp. a las ganancias. modif. dict. de may. titulo iii": {"name": "Modificación Declaración Jurada de Ganancias", "keywords": ["declaracion jurada", "impuesto a las ganancias", "ley 11683", "ley 27799", "simplificacion"]},
}

pending = json.loads(Path("pending_titles.json").read_text(encoding="utf-8"))

names_cache = load_ai_cache()
keywords_cache = load_ai_keywords_cache()

added = 0
missing = []
for entry in pending:
    vid = str(entry["ids"][0])
    if vid not in NAMES:
        missing.append((vid, entry["k"]))
        continue
    k = entry["k"]
    spec = NAMES[vid]
    name = spec["name"]
    if len(name.split()) > 8:
        raise SystemExit(f"NAME TOO LONG for {vid}: {name}")
    if len(name.split()) > 6:
        print(f"WARNING: {vid} name has {len(name.split())} words (over 6): {name}")
    names_cache[k] = name
    keywords_cache[k] = spec["keywords"]
    added += 1

if missing:
    raise SystemExit(f"MISSING NAMES for ids: {missing}")

for k, spec in EXTRA_KEYS.items():
    names_cache[k] = spec["name"]
    keywords_cache[k] = spec["keywords"]
    added += 1

save_ai_cache(names_cache)
save_ai_keywords_cache(keywords_cache)
print(f"Saved {added} names + keywords into ai_law_names.json / ai_law_keywords.json")
print(f"Cache now has {len(names_cache)} entries")
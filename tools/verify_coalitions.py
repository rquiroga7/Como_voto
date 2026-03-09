"""Quick verification of coalition assignments after generate_site.py."""
import json
import os
from collections import Counter

_BASE = os.path.join(os.path.dirname(__file__), "..")

with open(os.path.join(_BASE, "docs/data/legislators.json"), encoding="utf-8") as f:
    data = json.load(f)

co = Counter(l["co"] for l in data)
print("=== Coalition distribution ===")
for k, v in sorted(co.items()):
    print(f"  {k}: {v}")
print(f"  Total: {len(data)}")

# Spot-check some known legislators
print("\n=== Spot checks ===")
by_name = {l["n"]: l for l in data}
checks = [
    "MILEI, KARINA ELIZABETH",
    "MENEM, MARTIN IGNACIO",
    "CRISTINA ALVAREZ RODRIGUEZ, MARIA",
    "MACRI, MAURICIO",
    "MASSA, SERGIO TOMAS",
    "ESPERT, JOSE LUIS",
    "MOREAU, CECILIA",
    "RITONDO, CRISTIAN ADRIAN",
    "VILLARRUEL, VICTORIA EUGENIA",
]
for name in checks:
    if name in by_name:
        l = by_name[name]
        print(f"  {name}: co={l['co']}, bloc={l.get('b','?')}")
    else:
        # Try partial match
        matches = [n for n in by_name if name.split(",")[0] in n]
        if matches:
            for m in matches[:2]:
                l = by_name[m]
                print(f"  {m}: co={l['co']}, bloc={l.get('b','?')}")
        else:
            print(f"  {name}: NOT FOUND")

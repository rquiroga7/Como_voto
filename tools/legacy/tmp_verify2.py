import json

with open("docs/data/legislators.json", "r", encoding="utf-8") as f:
    legs = json.load(f)

print("=== Democracia para Siempre ===")
for l in legs:
    for t in l.get("t", []):
        if "democracia" in t.get("b", "").lower():
            print(f"  {l['n']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

print()
print("=== Campero, Picat, Tournier ===")
for name in ["CAMPERO", "PICAT", "TOURNIER"]:
    for l in legs:
        if name in l["n"].upper():
            for t in l.get("t", []):
                print(f"  {l['n']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")
            break

print()
print("=== LLA members (sample) ===")
for name in ["BORNORONI", "CORREA", "ALMIRON", "MAYORAZ", "VILLAVERDE", "BONGIOVANNI", "LEMOINE", "MILEI"]:
    for l in legs:
        if name in l["n"].upper():
            for t in l.get("t", []):
                if t["yf"] >= 2023:
                    print(f"  {l['n']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")
            break

print()
print("=== Provincias Unidas ===")
for l in legs:
    for t in l.get("t", []):
        if "provincias unidas" in t.get("b", "").lower():
            print(f"  {l['n']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

print()
print("=== Coalición Cívica current terms ===")
for l in legs:
    for t in l.get("t", []):
        if "coalici" in t.get("b", "").lower() and "c" in t.get("b", "").lower() and t["yf"] >= 2021:
            print(f"  {l['n']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

print()
cos = {}
for l in legs:
    co = l.get("co", "?")
    cos[co] = cos.get(co, 0) + 1
print("Coalition distribution:", dict(sorted(cos.items())))

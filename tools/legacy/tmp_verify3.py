import json, glob, os

base = "docs/data/legislators"
print("=== Democracia para Siempre ===")
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "democracia" in t.get("b", "").lower():
            name = d.get("name", "?")
            print(f"  {name} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

print()
print("=== Campero, Picat, Tournier ===")
for search in ["CAMPERO", "PICAT", "TOURNIER"]:
    for f in sorted(glob.glob(os.path.join(base, "*.json"))):
        if search in f.upper():
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            for t in d.get("terms", []):
                print(f"  {d['name']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")
            break

print()
print("=== LLA members ===")
for search in ["BORNORONI", "CORREA_LLANO", "ALMIRON", "MAYORAZ", "VILLAVERDE", "BONGIOVANNI", "LEMOINE", "MILEI"]:
    for f in sorted(glob.glob(os.path.join(base, "*.json"))):
        if search in f.upper():
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            for t in d.get("terms", []):
                if t["yf"] >= 2020:
                    print(f"  {d['name']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")
            break

print()
print("=== Provincias Unidas ===")
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "provincias unidas" in t.get("b", "").lower():
            print(f"  {d['name']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

print()
print("=== Coalición Cívica 2021+ ===")
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "coalici" in t.get("b", "").lower() and t["yf"] >= 2021:
            print(f"  {d['name']} co={t['co']} yf={t['yf']} yt={t['yt']} b={t['b']}")

# Coalition distribution from index
print()
with open("docs/data/legislators.json", "r", encoding="utf-8") as f:
    index = json.load(f)
cos = {}
for l in index:
    co = l.get("co", "?")
    cos[co] = cos.get(co, 0) + 1
print("Coalition distribution:", dict(sorted(cos.items())))

import json, glob, os

base = "docs/data/legislators"
print("=== Pichetto mandates ===")
for f in glob.glob(os.path.join(base, "*PICHETTO*.json")):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        print(f"  {d['name']} yf={t['yf']} yt={t['yt']} b={t['b']} co={t.get('co')} co_electoral={t.get('co_electoral')}")

print("\n=== Encuentro Federal mandates ===")
for f in glob.glob(os.path.join(base, "*.json")):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "encuentro federal" in t.get("b", "").lower():
            print(f"  {d['name']} yf={t['yf']} yt={t['yt']} b={t['b']} co={t.get('co')} co_electoral={t.get('co_electoral')}")

print("\n=== Mandates with fallback to bloc ===")
for f in glob.glob(os.path.join(base, "*.json")):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if t.get('co_electoral') == t.get('co'):
            print(f"  {d['name']} yf={t['yf']} yt={t['yt']} b={t['b']} co={t.get('co')} co_electoral={t.get('co_electoral')}")

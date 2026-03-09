"""Audit coalition classifications: sources, mismatches, and specific problem cases."""
import json, os, glob

base = "docs/data/legislators"

# 1. Check Encuentro Federal members
print("=" * 60)
print("ENCUENTRO FEDERAL members")
print("=" * 60)
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "encuentro federal" in t.get("b", "").lower():
            print(f"  {d['name']:40s} co={t['co']:6s} yf={t['yf']} yt={t['yt']} b={t['b']}")

# 2. Check Provincias Unidas members  
print()
print("=" * 60)
print("PROVINCIAS UNIDAS members")
print("=" * 60)
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    for t in d.get("terms", []):
        if "provincias unidas" in t.get("b", "").lower():
            print(f"  {d['name']:40s} co={t['co']:6s} yf={t['yf']} yt={t['yt']} b={t['b']}")

# 3. Check Pichetto
print()
print("=" * 60)
print("PICHETTO")
print("=" * 60)
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    if "PICHETTO" in f.upper():
        with open(f, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        print(f"  Name: {d['name']}")
        print(f"  Overall co: {d.get('coalition')}")
        for t in d.get("terms", []):
            print(f"    term: co={t['co']:6s} yf={t['yf']} yt={t['yt']} b={t['b']}")
        # Check election data
        el = d.get("election_party")
        print(f"  election_party: {el}")

# 4. Classification source audit
print()
print("=" * 60)
print("CLASSIFICATION SOURCE AUDIT")
print("=" * 60)
# Load election data to check which legislators have election matches
with open("data/election_legislators.json", "r", encoding="utf-8") as f:
    elections = json.load(f)

total_terms = 0
election_matched = 0
bloc_fallback = 0
# Can't easily tell from output - let's check the compute_terms logic differently
# Instead, count how many current legislators have election_party set
with open("docs/data/legislators.json", "r", encoding="utf-8") as f:
    idx = json.load(f)

print(f"Total legislators in index: {len(idx)}")

# Check individual files for election_party
has_election = 0
no_election = 0
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    ep = d.get("election_party")
    if ep:
        has_election += 1
    else:
        no_election += 1
print(f"With election_party: {has_election}")
print(f"Without election_party: {no_election}")

# 5. Show all LLA-classified legislators with their blocs
print()
print("=" * 60)
print("ALL CURRENT LLA-CLASSIFIED (from index)")
print("=" * 60)
lla_legs = [l for l in idx if l.get("co") == "LLA"]
for l in sorted(lla_legs, key=lambda x: x["n"]):
    print(f"  {l['n']:40s} b={l.get('b','?'):40s}")

# 6. Show all current PRO-classified legislators  
print()
print("=" * 60)
print("CURRENT PRO-CLASSIFIED with 2024+ terms")
print("=" * 60)
for f in sorted(glob.glob(os.path.join(base, "*.json"))):
    with open(f, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    active_2024 = [t for t in d.get("terms", []) if t["yt"] >= 2024]
    if active_2024 and d.get("coalition") == "PRO":
        latest = max(active_2024, key=lambda t: t["yt"])
        print(f"  {d['name']:40s} co={latest['co']:6s} b={latest['b']}")

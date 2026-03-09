import json, re
d = json.load(open('docs/data/legislators.json', encoding='utf-8'))
el = json.load(open('data/election_legislators.json', encoding='utf-8'))

# Check the 3 remaining LLA->OTROS
for nm in ['CAMPERO', 'PICAT', 'TOURNIER']:
    for l in d:
        if nm in l['n'].upper():
            safe = re.sub(r'[^A-Z0-9_]', '_', l['k'])[:80]
            with open(f'docs/data/legislators/{safe}.json', encoding='utf-8') as f:
                det = json.load(f)
            print(f"=== {l['n']} ===")
            print(f"  terms: {det.get('terms')}")
            print(f"  election_party: {det.get('election_party')}")
            # Check election data
            for yr in ['2021', '2023']:
                for ch in ['diputados', 'senadores']:
                    for c in el.get(yr,{}).get(ch,[]):
                        if nm.lower() in c['name'].lower():
                            print(f"  election {yr} {ch}: {c['name']} co={c['coalition']} alliance={c['alliance']} party={c.get('party_code','?')}")
            break

# Check Democracia para Siempre members
print("\n=== Democracia para Siempre detailed terms ===")
for l in d:
    if 'democracia para siempre' in l.get('b','').lower():
        safe = re.sub(r'[^A-Z0-9_]', '_', l['k'])[:80]
        with open(f'docs/data/legislators/{safe}.json', encoding='utf-8') as f:
            det = json.load(f)
        terms = det.get('terms', [])
        print(f"  {l['n']} co={l['co']}  terms={terms}")

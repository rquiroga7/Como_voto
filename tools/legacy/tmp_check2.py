import json, re

d = json.load(open('docs/data/legislators.json', encoding='utf-8'))

# Check a few specific cases in detail files
for name_part in ['BORNORONI', 'LEMOINE', 'MAYORAZ', 'ALMIRON']:
    for l in d:
        if name_part in l['n'].upper():
            safe = re.sub(r'[^A-Z0-9_]', '_', l['k'])[:80]
            try:
                with open(f'docs/data/legislators/{safe}.json', encoding='utf-8') as f:
                    det = json.load(f)
                print(f"=== {l['n']} ===")
                print(f"  coalition: {det.get('coalition')}")
                print(f"  election_party: {det.get('election_party')}")
                print(f"  bloc: {det.get('bloc')}")
                print(f"  terms: {json.dumps(det.get('terms',[]), ensure_ascii=False)}")
            except FileNotFoundError:
                print(f"  FILE NOT FOUND: {safe}")
            break

# Also check election data for these legislators
print("\n=== Election data for LLA members ===")
el = json.load(open('data/election_legislators.json', encoding='utf-8'))
for yr in ['2021', '2023']:
    for ch in ['diputados', 'senadores']:
        for c in el.get(yr, {}).get(ch, []):
            name = c['name'].upper()
            for nm in ['BORNORONI', 'LEMOINE', 'MAYORAZ', 'ALMIRON', 'VILLAVERDE']:
                if nm in name:
                    print(f"  {yr} {ch}: {c['name']}  alliance={c.get('alliance')}  coalition={c.get('coalition')}  party={c.get('party_code','?')}  suplente={c.get('suplente',False)}")

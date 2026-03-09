import json
el = json.load(open('data/election_legislators.json', encoding='utf-8'))
print('=== 2023 coalition counts ===')
for ch in ['diputados', 'senadores']:
    coalitions = {}
    for c in el.get('2023',{}).get(ch,[]):
        co = c['coalition']
        coalitions[co] = coalitions.get(co, 0) + 1
    print(f'  {ch}: {coalitions}')

print('\n=== Specific LLA members ===')
for nm in ['Bornoroni', 'Lemoine', 'Mayoraz', 'Villaverde', 'Almiron']:
    for ch in ['diputados', 'senadores']:
        for c in el.get('2023',{}).get(ch,[]):
            if nm.lower() in c['name'].lower():
                print(f"  {c['name']}  co={c['coalition']}  party={c.get('party_code','?')}  alliance={c['alliance']}")

#!/usr/bin/env python3
"""Check how many legislators would be affected by trailing-AUSENTE fix."""
import json, re, os
from datetime import datetime

idx = json.load(open('docs/data/legislators.json', encoding='utf-8'))

def parse_date(d):
    try: return datetime.strptime(d.strip(), '%d/%m/%Y - %H:%M')
    except:
        try: return datetime.strptime(d.strip()[:10], '%d/%m/%Y')
        except: return datetime.min

affected = 0
big_impact = []
# Only check legislators with notably low presentismo (< 80%)
candidates = [l for l in idx if l.get('pres') is not None and l['pres'] < 80 and l.get('tv', 0) > 20]
print(f"Checking {len(candidates)} legislators with pres < 80%...")
for i, l in enumerate(candidates):
    safe = re.sub(r'[^A-Z0-9_]', '_', l['k'])[:80]
    path = f'docs/data/legislators/{safe}.json'
    if not os.path.exists(path): continue
    d = json.load(open(path, encoding='utf-8'))
    votes = d.get('votes', [])
    if not votes: continue
    non_aus = [v for v in votes if v.get('v') != 'AUSENTE']
    if not non_aus: continue
    last_dt = max(parse_date(v.get('d','')) for v in non_aus)
    trailing = sum(1 for v in votes if v.get('v')=='AUSENTE' and parse_date(v.get('d','')) > last_dt)
    if trailing >= 10:
        old_pres = l.get('pres', 0) or 0
        new_total = len(votes) - trailing
        new_pres = round(len(non_aus) / new_total * 100, 1) if new_total > 0 else 0
        diff = new_pres - old_pres
        if diff > 2:
            big_impact.append((l['n'], old_pres, new_pres, trailing, len(votes)))
            affected += 1

big_impact.sort(key=lambda x: x[2]-x[1], reverse=True)
print(f'Legislators with 10+ trailing absences and >2pp impact: {affected}')
for name, old, new, trail, total in big_impact[:25]:
    print(f'  {name:40s} {old:5.1f}% -> {new:5.1f}% (+{new-old:.1f}pp)  trailing={trail}/{total}')

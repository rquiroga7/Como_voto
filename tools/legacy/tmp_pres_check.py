#!/usr/bin/env python3
"""Temporary script to investigate presentismo edge cases."""
import json

idx = json.load(open('docs/data/legislators.json', encoding='utf-8'))

# Find legislators with very low presentismo
low_pres = [l for l in idx if l.get('pres') is not None and l['pres'] < 30 and l.get('tv', 0) > 50]
low_pres.sort(key=lambda l: l['pres'])
print("=== LOWEST PRESENTISMO (tv>50) ===")
for l in low_pres[:15]:
    print(f"  {l['n']:40s} pres={l['pres']:5.1f}%  tv={l['tv']:4d}  aus={l['aus']:4d}  co={l['co']}")

# Now check the detail files for the worst cases to see their yearly_stats
print("\n=== DETAIL CHECK ===")
for l in low_pres[:5]:
    key = l['k']
    import re
    safe = re.sub(r'[^A-Z0-9_]', '_', key)[:80]
    try:
        detail = json.load(open(f'docs/data/legislators/{safe}.json', encoding='utf-8'))
        terms = detail.get('terms', [])
        yearly = detail.get('yearly_stats', {})
        print(f"\n--- {l['n']} ---")
        print(f"  Terms: {[(t['yf'], t['yt'], t['ch']) for t in terms]}")
        for yr in sorted(yearly.keys()):
            s = yearly[yr]
            total = s.get('total', 0)
            aus = s.get('AUSENTE', 0)
            pres = total - aus
            pct = round(pres / total * 100) if total > 0 else 0
            print(f"  {yr}: total={total:3d}  present={pres:3d}  ausente={aus:3d}  pres%={pct:3d}%")
    except Exception as e:
        print(f"  Error: {e}")

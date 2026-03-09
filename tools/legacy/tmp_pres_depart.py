#!/usr/bin/env python3
"""Check early-departure presentismo patterns."""
import json

for name in ["MACRI__MAURICIO", "MENEM__CARLOS_SAUL", "KIRCHNER__NESTOR_CARLOS"]:
    try:
        d = json.load(open(f'docs/data/legislators/{name}.json', encoding='utf-8'))
    except FileNotFoundError:
        print(f"Not found: {name}")
        continue
    
    print(f"\n=== {d['name']} ===")
    print(f"Terms: {[(t['yf'], t['yt'], t['ch']) for t in d['terms']]}")
    
    for yr in sorted(d['yearly_stats'].keys()):
        s = d['yearly_stats'][yr]
        t = s.get('total', 0)
        aus = s.get('AUSENTE', 0)
        print(f"  {yr}: total={t:3d}  present={t-aus:3d}  ausente={aus:3d}")
    
    votes = d.get('votes', [])
    non_aus = [v for v in votes if v.get('v') != 'AUSENTE']
    all_aus = [v for v in votes if v.get('v') == 'AUSENTE']
    
    if non_aus:
        last_active = max(non_aus, key=lambda v: v.get('d', ''))
        last_date = last_active.get('d', '?')
        aus_after = len([v for v in all_aus if v.get('d', '') > last_date])
        print(f"  Last active vote: {last_date}")
        print(f"  AUSENTE after last active: {aus_after} / {len(all_aus)} total AUSENTE")
        print(f"  If excluded: presentismo would be {len(non_aus)}/{len(votes)-aus_after} = {round(len(non_aus)/(len(votes)-aus_after)*100,1) if len(votes)-aus_after>0 else 0}%")
        print(f"  Current: {round(len(non_aus)/len(votes)*100,1) if votes else 0}%")

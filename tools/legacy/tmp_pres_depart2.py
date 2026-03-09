#!/usr/bin/env python3
"""Check early-departure presentismo patterns with proper date parsing."""
import json
import re
from datetime import datetime

def parse_date(d):
    """Parse DD/MM/YYYY - HH:MM date string."""
    try:
        return datetime.strptime(d.strip(), "%d/%m/%Y - %H:%M")
    except:
        try:
            return datetime.strptime(d.strip()[:10], "%d/%m/%Y")
        except:
            return datetime.min

for name in ["MACRI__MAURICIO", "MENEM__CARLOS_SAUL", "KIRCHNER__NESTOR_CARLOS",
             "QUINTAR__AMADO", "SCIOLI__DANIEL_OSVALDO"]:
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
        last_active = max(non_aus, key=lambda v: parse_date(v.get('d', '')))
        last_date = parse_date(last_active.get('d', ''))
        aus_after = [v for v in all_aus if parse_date(v.get('d', '')) > last_date]
        print(f"  Last active vote: {last_active.get('d', '?')}")
        print(f"  AUSENTE after last active: {len(aus_after)} / {len(all_aus)} total AUSENTE")
        effective_total = len(votes) - len(aus_after)
        effective_present = len(non_aus)
        if effective_total > 0:
            print(f"  Adjusted presentismo: {effective_present}/{effective_total} = {round(effective_present/effective_total*100,1)}%")
        print(f"  Current presentismo: {round(len(non_aus)/len(votes)*100,1) if votes else 0}%")

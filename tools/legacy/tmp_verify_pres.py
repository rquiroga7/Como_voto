#!/usr/bin/env python3
"""Verify presentismo fix in generated data."""
import json

idx = json.load(open('docs/data/legislators.json', encoding='utf-8'))
for name in ['KIRCHNER', 'QUINTAR', 'MACRI, Mauricio', 'MENEM', 'SABBATELLA', 'ARGUELLO']:
    matches = [l for l in idx if name.upper() in l['n'].upper()]
    for l in matches[:1]:
        pres = l.get('pres')
        tv = l.get('tv', 0)
        aus = l.get('aus', 0)
        print(f"  {l['n']:40s} pres={pres}%  tv={tv}  aus={aus}")

# Also check trailing_ausente field in detail files
print("\n=== Trailing AUSENTE in detail files ===")
for fname in ['KIRCHNER__NESTOR_CARLOS', 'QUINTAR__AMADO', 'MACRI__MAURICIO', 'SABBATELLA__MARTIN']:
    try:
        d = json.load(open(f'docs/data/legislators/{fname}.json', encoding='utf-8'))
        ta = d.get('trailing_ausente', 'MISSING')
        print(f"  {d['name']:40s} trailing_ausente={ta}")
    except FileNotFoundError:
        print(f"  {fname}: not found")

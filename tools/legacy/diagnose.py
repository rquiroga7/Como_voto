"""Diagnose what data we have and why years are missing."""
import json, os, re
from pathlib import Path

dip_dir = Path('data/diputados')
sen_dir = Path('data/senadores')

years_dip = {}
years_sen = {}
ids_dip = []

for f in sorted(dip_dir.glob('*.json')):
    d = json.load(open(f, encoding='utf-8'))
    date = d.get('date','')
    m = re.search(r'(\d{4})', date)
    yr = m.group(1) if m else '?'
    years_dip[yr] = years_dip.get(yr, 0) + 1
    ids_dip.append(int(f.stem))

for f in sorted(sen_dir.glob('*.json')):
    d = json.load(open(f, encoding='utf-8'))
    date = d.get('date','')
    m = re.search(r'(\d{4})', date)
    yr = m.group(1) if m else '?'
    years_sen[yr] = years_sen.get(yr, 0) + 1

print('DIPUTADOS by year:', dict(sorted(years_dip.items())))
print('SENADORES by year:', dict(sorted(years_sen.items())))
if ids_dip:
    print(f'Diputados IDs: min={min(ids_dip)}, max={max(ids_dip)}, count={len(ids_dip)}')
print(f'Senadores files: {len(list(sen_dir.glob("*.json")))}')

# Check what HCDN IDs look like for different years
print('\nSample diputados by ID range:')
for f in sorted(dip_dir.glob('*.json')):
    fid = int(f.stem)
    if fid in [1, 2, 50, 100, 150, 170]:
        d = json.load(open(f, encoding='utf-8'))
        print(f'  ID {fid}: date={d.get("date","?")[:15]}, title={d.get("title","?")[:60]}')

# Check the index files
dip_idx = Path('data/diputados_index.json')
sen_idx = Path('data/senadores_index.json')
if dip_idx.exists():
    idx = json.load(open(dip_idx, encoding='utf-8'))
    print(f'\nDiputados index: {len(idx)} entries')
if sen_idx.exists():
    idx = json.load(open(sen_idx, encoding='utf-8'))
    print(f'Senadores index: {len(idx)} entries')

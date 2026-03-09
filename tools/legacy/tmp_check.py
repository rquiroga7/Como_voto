import json

d = json.load(open('docs/data/legislators.json', encoding='utf-8'))

print("=== Reported misclassifications ===")
names = ['BORNORONI', 'CORREA LLANO', 'ALMIRON', 'MAYORAZ', 'VILLAVERDE', 'BONGIOVANNI']
for l in d:
    nu = l['n'].upper()
    for nm in names:
        if nm in nu:
            by = {co: v.get('b','') for co, v in l.get('by_co', {}).items()}
            print(f"  {l['n']}  co={l['co']}  b={l.get('b','')}  by_co={by}")
            break

print("\n=== Coalición Cívica bloc legislators (current terms) ===")
for l in d:
    bl = l.get('b','').lower()
    if 'coalici' in bl:
        by = {co: v.get('b','') for co, v in l.get('by_co', {}).items()}
        print(f"  {l['n']}  co={l['co']}  b={l['b']}  by_co={by}")

print("\n=== Democracia para Siempre bloc ===")
for l in d:
    bl = l.get('b','').lower()
    if 'democracia' in bl:
        by = {co: v.get('b','') for co, v in l.get('by_co', {}).items()}
        print(f"  {l['n']}  co={l['co']}  b={l['b']}  by_co={by}")

print("\n=== Provincias Unidas bloc ===")
for l in d:
    bl = l.get('b','').lower()
    if 'provincias unidas' in bl:
        by = {co: v.get('b','') for co, v in l.get('by_co', {}).items()}
        print(f"  {l['n']}  co={l['co']}  b={l['b']}  by_co={by}")

print("\n=== All LLA legislators going to OTROS ===")
# Check who has LLA election data but ends up OTROS
for l in d:
    if l['co'] == 'OTROS':
        bl = l.get('b','').lower()
        if 'libertad avanza' in bl:
            print(f"  {l['n']}  co={l['co']}  b={l.get('b','')}")

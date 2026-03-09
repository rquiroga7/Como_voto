import json
d = json.load(open('docs/data/legislators.json', encoding='utf-8'))

print("=== Previously misclassified LLA members ===")
for nm in ['BORNORONI', 'CORREA LLANO', 'ALMIRON', 'MAYORAZ', 'VILLAVERDE', 'BONGIOVANNI', 'LEMOINE', 'MILEI']:
    for l in d:
        if nm in l['n'].upper():
            by = {co: v.get('b','') for co, v in l.get('by_co', {}).items()}
            print(f"  {l['n']}  co={l['co']}  by_co={by}")
            break

print("\n=== Democracia para Siempre ===")
for l in d:
    if 'democracia para siempre' in l.get('b','').lower():
        print(f"  {l['n']}  co={l['co']}  b={l['b']}")

print("\n=== Coalición Cívica (2024+ terms) ===")
for l in d:
    if 'coalición cívica' in l.get('b','').lower():
        for co, v in l.get('by_co', {}).items():
            if co in ('LLA',):
                print(f"  {l['n']}  co={l['co']}  has_LLA_period")

print("\n=== LLA bloc still going OTROS ===")
count = 0
for l in d:
    if l['co'] == 'OTROS' and 'libertad avanza' in l.get('b','').lower():
        count += 1
        print(f"  {l['n']}  co={l['co']}  b={l['b']}")
print(f"  Total: {count}")

print("\n=== Coalition distribution ===")
from collections import Counter
co_counts = Counter(l['co'] for l in d)
for k, v in sorted(co_counts.items()):
    print(f"  {k}: {v}")
print(f"  Total: {len(d)}")

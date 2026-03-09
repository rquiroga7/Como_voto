import json, pprint
p='docs/data/legislators/RECALDE__HECTOR_PEDRO.json'
with open(p,'r',encoding='utf-8') as f:
    d=json.load(f)
ya=d.get('yearly_alignment',{})
print('years:', sorted(ya.keys()))
for y in sorted(ya.keys()):
    print('---', y)
    pprint.pprint(ya[y])

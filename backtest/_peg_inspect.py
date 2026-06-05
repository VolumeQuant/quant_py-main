import json, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

f = sorted(glob.glob('state/ranking_2024*.json'))[100]
d = json.load(open(f, encoding='utf-8'))
items = d if isinstance(d, list) else d.get('rankings', [])
print('file', f)
print('n items', len(items))
it = items[0]
print('--- item[0] keys/values ---')
for k, v in it.items():
    print('  ', repr(k), '=', repr(v))

# union of keys across items
allkeys = set()
for it in items:
    allkeys.update(it.keys())
print('--- union of all keys ---')
print(sorted(allkeys))

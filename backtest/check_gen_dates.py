import json, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

print('=== BT_EXT (bt_extended) 생성일 ===')
files = sorted(glob.glob('C:/dev/backtest/bt_extended/ranking_*.json'))
print(f'개수: {len(files)}')
print('첫 3개:')
for f in files[:3]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')
print('마지막 3개:')
for f in files[-3:]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')

print('\n=== BT_EXT_D (bt_extended_defense) 생성일 ===')
files = sorted(glob.glob('C:/dev/backtest/bt_extended_defense/ranking_*.json'))
print(f'개수: {len(files)}')
for f in files[:3]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')
for f in files[-3:]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')

print('\n=== STATE (C:/dev/state) 생성일 ===')
files = sorted(glob.glob('C:/dev/state/ranking_*.json'))
print(f'개수: {len(files)}')
for f in files[:3]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')
print('중간 (2023-06):')
for f in [x for x in files if '20230601' <= x[-13:-5] <= '20230610'][:3]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')
for f in files[-3:]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')

print('\n=== STATE_D (C:/dev/state/defense) 생성일 ===')
files = sorted(glob.glob('C:/dev/state/defense/ranking_*.json'))
print(f'개수: {len(files)}')
for f in files[:3]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')
for f in files[-3:]:
    d = json.load(open(f, 'r', encoding='utf-8'))
    print(f'  {f[-13:]}: gen={d.get("generated_at","NONE")[:19]}')

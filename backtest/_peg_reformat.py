import json, glob, sys
sys.stdout.reconfigure(encoding='utf-8')
n=0
for f in glob.glob('state/ranking_*.json'):
    try:
        d=json.load(open(f,encoding='utf-8'))
        json.dump(d, open(f,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
        n+=1
    except Exception as e:
        print('skip',f,e)
print(f'{n} 파일 indent=2 재포맷')

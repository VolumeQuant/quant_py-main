# -*- coding: utf-8 -*-
"""TOP20 종목을 가장 잘 반영하는 ETF 탐색 (순위 가중 커버리지).
점수 = Σ over held(top20)  (21-순위) × ETF내_비중%.
2026-06-11. KRX 공식 구성종목(pykrx get_etf_portfolio_deposit_file) 기준."""
import sys, io, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import krx_auth; krx_auth.login()
from pykrx import stock

DATE = '20260610'
# TOP20 (순위: 티커)
TOP20 = {
    1:'080220',2:'000660',3:'187870',4:'005930',5:'219130',6:'031330',7:'049630',
    8:'131290',9:'025560',10:'043260',11:'356860',12:'452280',13:'037460',14:'161390',
    15:'089970',16:'007810',17:'382800',18:'053610',19:'281820',20:'067310'}
NAME = {'080220':'제주반도체','000660':'SK하이닉스','187870':'디바이스','005930':'삼성전자',
    '219130':'타이거일렉','031330':'에스에이엠티','049630':'재영솔루텍','131290':'티에스이',
    '025560':'미래산업','043260':'성호전자','356860':'티엘비','452280':'한선엔지니어링',
    '037460':'삼지전자','161390':'한국타이어','089970':'브이엠','007810':'코리아써키트',
    '382800':'지앤비에스에코','053610':'프로텍','281820':'케이씨텍','067310':'하나마이크론'}
rank_of = {t:r for r,t in TOP20.items()}
rw = lambda t: 21 - rank_of[t]  # rank weight

# 후보 ETF (국내 반도체/코스닥/테크/성장/중소형)
CANDS = ['0182R0','469150','380340','354500','0005G0','0191S0','469790','316670',
'226980','395160','471990','266370','244620','275280','091160','325010','275300',
'373490','229200','364690','0163Y0','438740','0191B0','301400','0166N0','0093A0',
'326240','388420','270810','0151P0','0167A0','455850','475300','475310','444200',
'450910','0192T0','139260','471760','365040','091230','396500','232080','261060',
'0204S0','471780','494220','470310','476000','474590','476260','395270','304770',
'448570','487750','486240','442090','0053M0','292150','229720','228820','407310',
'140580','104520','227570','147970','410870','385710']

rows = []
for i, etf in enumerate(CANDS):
    try:
        df = stock.get_etf_portfolio_deposit_file(etf, DATE)
        nm = stock.get_etf_ticker_name(etf)
        if df is None or len(df) == 0:
            continue
        wcol = '비중' if '비중' in df.columns else df.columns[-1]
        held = []
        for t in TOP20.values():
            if t in df.index:
                w = float(df.loc[t, wcol]) if not hasattr(df.loc[t, wcol],'__len__') else float(df.loc[t, wcol].iloc[0])
                held.append((t, w))
        score = sum(rw(t)*w for t,w in held)
        wsum = sum(w for _,w in held)
        rows.append((etf, nm, len(held), wsum, score, sorted(held, key=lambda x:rank_of[x[0]])))
    except Exception as e:
        print(f'  [skip {etf}] {e}', file=sys.stderr)
    time.sleep(0.5)

rows.sort(key=lambda x: -x[4])
print(f'\n=== TOP20 커버리지 순위 (점수=Σ(21-순위)×비중%, {DATE}) ===')
print(f"{'ETF명':<26}{'코드':<8}{'#':>3}{'비중합':>7}{'점수':>7}  보유종목(순위)")
for etf, nm, n, wsum, sc, held in rows[:18]:
    hs = ' '.join(f'{NAME[t]}{rank_of[t]}({w:.0f}%)' for t,w in held)
    print(f"{nm:<26}{etf:<8}{n:>3}{wsum:>6.0f}%{sc:>7.0f}  {hs}")

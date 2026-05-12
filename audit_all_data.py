"""DART, FnGuide, market_cap, fundamentals, sectors, kospi/kosdaq, state 전수 검증.

목적: 5/13 새벽 사고 후 OHLCV 외 데이터도 결손 있는지 확인.
"""
import sys, os, json
from pathlib import Path
from datetime import datetime
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path('.')
CACHE = PROJECT / 'data_cache'

report = []

def log(msg):
    print(msg, flush=True)
    report.append(msg)

log('='*60)
log('데이터 전수 검사 보고서')
log(f'생성 시각: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
log('='*60)

# ================================================================
# 1. OHLCV (refill 백그라운드 진행 중 — 스냅샷)
# ================================================================
log('\n[1] OHLCV')
try:
    op = CACHE / 'all_ohlcv_REFILL_progress.parquet'
    om = CACHE / 'all_ohlcv_20170601_20260512.parquet'
    target = op if op.exists() else om
    o = pd.read_parquet(target)
    nz = o.notna().sum(axis=1)
    log(f'  파일: {target.name}')
    log(f'  shape: {o.shape}, 범위: {o.index.min().date()} ~ {o.index.max().date()}')
    log(f'  정상(≥1500종목): {(nz>=1500).sum()} / {len(nz)}')
    log(f'  결손(<1500종목): {(nz<1500).sum()}')
    log(f'  ⚠️ 결손 — 백그라운드 refill 진행 중')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 2. DART (fs_dart_*.parquet)
# ================================================================
log('\n[2] DART (fs_dart_*.parquet)')
try:
    fs_dart_files = [f for f in CACHE.glob('fs_dart_*.parquet') if 'backup' not in f.name]
    log(f'  종목 파일 수: {len(fs_dart_files)}')
    # rcept_dt 분포
    rcept_dates = []
    no_rcept = 0
    empty = 0
    sample_rows = 0
    for fp in fs_dart_files[:100]:  # 표본 100개로 빠르게
        try:
            df = pd.read_parquet(fp)
            if df.empty:
                empty += 1
                continue
            if 'rcept_dt' not in df.columns:
                no_rcept += 1
                continue
            mx = df['rcept_dt'].dropna().max()
            if pd.notna(mx):
                rcept_dates.append(mx)
            sample_rows += len(df)
        except: empty += 1
    if rcept_dates:
        ser = pd.Series(rcept_dates)
        log(f'  표본 100개 rcept_dt: min={ser.min()}, max={ser.max()}, median={ser.median()}')
    log(f'  표본 빈 파일: {empty}, rcept_dt 없는 파일: {no_rcept}')
    log(f'  표본 평균 행 수: {sample_rows//max(1,(100-empty))} per 종목')
    # 5/12 최신성 — 최근 30일 내 rcept_dt 있는 종목 비율
    recent_thresh = pd.Timestamp('2026-04-13')
    recent_count = 0
    total_check = 0
    for fp in fs_dart_files:
        try:
            df = pd.read_parquet(fp)
            if 'rcept_dt' not in df.columns or df.empty:
                continue
            total_check += 1
            if df['rcept_dt'].dropna().max() >= recent_thresh:
                recent_count += 1
        except: pass
    log(f'  최근 30일(>={recent_thresh.date()}) rcept_dt 보유 종목: {recent_count}/{total_check}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 3. FnGuide (fs_fnguide_*.parquet)
# ================================================================
log('\n[3] FnGuide (fs_fnguide_*.parquet)')
try:
    fn_files = list(CACHE.glob('fs_fnguide_*.parquet'))
    log(f'  종목 파일 수: {len(fn_files)}')
    # 기준일 분포
    max_dates = []
    empty = 0
    for fp in fn_files[:200]:
        try:
            df = pd.read_parquet(fp)
            if df.empty:
                empty += 1
                continue
            if '기준일' in df.columns:
                mx = df['기준일'].dropna().max()
                if pd.notna(mx):
                    max_dates.append(mx)
        except: empty += 1
    if max_dates:
        ser = pd.Series(max_dates)
        log(f'  표본 200개 기준일 max: min={ser.min()}, max={ser.max()}, median={ser.median()}')
    log(f'  표본 빈 파일: {empty}')
    # 표본 종목 컬럼 구조
    if fn_files:
        s = pd.read_parquet(fn_files[0])
        log(f'  표본 컬럼: {s.columns.tolist()}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 4. market_cap
# ================================================================
log('\n[4] market_cap')
try:
    mc_files = sorted(CACHE.glob('market_cap_*.parquet'))
    log(f'  파일 수: {len(mc_files)}, 범위: {mc_files[0].stem} ~ {mc_files[-1].stem}')
    # 종목 수 분포
    counts = []
    for fp in mc_files:
        try:
            df = pd.read_parquet(fp)
            counts.append((fp.stem, len(df)))
        except: pass
    df_c = pd.DataFrame(counts, columns=['name','n'])
    log(f'  파일별 종목 수: min={df_c["n"].min()}, max={df_c["n"].max()}, median={df_c["n"].median():.0f}, mean={df_c["n"].mean():.0f}')
    # 결손 의심 (<2000)
    suspect = df_c[df_c['n'] < 2000]
    log(f'  <2000종목 파일: {len(suspect)} (예: {suspect["name"].head(5).tolist()})')
    # 최근 7일
    recent = sorted([f for f in mc_files if 'ALL_2026' in f.name])[-7:]
    log(f'  최근 ALL_2026 7개:')
    for fp in recent:
        df = pd.read_parquet(fp)
        log(f'    {fp.stem}: {len(df)}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 5. fundamentals
# ================================================================
log('\n[5] fundamentals')
try:
    fd_files = sorted(CACHE.glob('fundamentals_*.parquet'))
    log(f'  파일 수: {len(fd_files)}')
    for fp in fd_files:
        df = pd.read_parquet(fp)
        log(f'  {fp.stem}: shape={df.shape}')
    log(f'  ⚠️ 99 종목만 — 원본부터 결손일 가능성, git log 확인 필요')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 6. sectors (krx_sector_*)
# ================================================================
log('\n[6] sectors (krx_sector_*)')
try:
    sec_files = sorted(CACHE.glob('krx_sector_*.parquet'))
    log(f'  파일 수: {len(sec_files)}, 범위: {sec_files[0].stem} ~ {sec_files[-1].stem}')
    # 최근 7일
    recent = [f for f in sec_files if '2026' in f.name][-10:]
    for fp in recent:
        df = pd.read_parquet(fp)
        log(f'    {fp.stem}: {df.shape}, columns: {df.columns.tolist()[:5]}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 7. KOSPI/KOSDAQ
# ================================================================
log('\n[7] KOSPI/KOSDAQ')
try:
    for n in ['kospi_yf','kosdaq_yf']:
        df = pd.read_parquet(CACHE/f'{n}.parquet')
        log(f'  {n}: shape={df.shape}, 범위 {df.index.min().date()} ~ {df.index.max().date()}, cols={df.columns.tolist()}')
        # NaN 비율
        nan_ratio = df.isna().any(axis=1).sum() / len(df) * 100
        log(f'    NaN 행 비율: {nan_ratio:.1f}%')
        # 최근 5일
        log(f'    최근 5일: {df.tail(5).index.tolist()}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 8. state ranking (boost + defense)
# ================================================================
log('\n[8] state ranking (boost + defense)')
try:
    for dname in ['state', 'state/defense']:
        files = sorted((PROJECT/dname).glob('ranking_*.json'))
        log(f'  {dname}: {len(files)} 파일')
        # 일자별 연속성 검증
        dates = sorted([f.stem[-8:] for f in files])
        # 최근 5개
        log(f'    최근 5: {dates[-5:]}')
        # 빠진 거래일 — kospi 거래일과 비교
        kospi = pd.read_parquet(CACHE/'kospi_yf.parquet')
        kdates = set(kospi.index.strftime('%Y%m%d'))
        kdates_in_range = {d for d in kdates if d >= dates[0] and d <= dates[-1]}
        sdates = set(dates)
        missing = sorted(kdates_in_range - sdates)
        log(f'    빠진 거래일: {len(missing)}')
        if missing[:5]:
            log(f'      예: {missing[:5]}')
        # 종목 수 분포
        counts = []
        for fp in files:
            try:
                s = json.load(open(fp, encoding='utf-8'))
                counts.append(len(s.get('rankings', [])))
            except: pass
        ser = pd.Series(counts)
        log(f'    종목 수: min={ser.min()}, max={ser.max()}, mean={ser.mean():.0f}, median={ser.median():.0f}')
        log(f'    <100종목 파일: {(ser<100).sum()} (정상 320+)')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 9. bt_extended (boost + defense)
# ================================================================
log('\n[9] bt_extended (boost + defense)')
try:
    for dname in ['backtest/bt_extended', 'backtest/bt_extended_defense']:
        files = sorted((PROJECT/dname).glob('ranking_*.json'))
        if not files: continue
        log(f'  {dname}: {len(files)} 파일 ({files[0].stem[-8:]} ~ {files[-1].stem[-8:]})')
        counts = []
        for fp in files:
            try:
                s = json.load(open(fp, encoding='utf-8'))
                counts.append(len(s.get('rankings', [])))
            except: pass
        ser = pd.Series(counts)
        log(f'    종목 수: min={ser.min()}, max={ser.max()}, mean={ser.mean():.0f}')
except Exception as e:
    log(f'  ERROR: {e}')

# ================================================================
# 10. regime_state.json
# ================================================================
log('\n[10] regime_state.json')
try:
    rs = json.load(open(PROJECT/'regime_state.json', encoding='utf-8'))
    log(f'  regime: {rs.get("current_regime","?")}, switch_count={rs.get("confirm_count","?")}')
    log(f'  last_eval: {rs.get("last_eval_date","?")}, rule={rs.get("rule","?")}')
except Exception as e:
    log(f'  ERROR: {e}')

log('\n='*60)
log('검사 종료')
log('='*60)

# 저장
out = PROJECT / 'DATA_AUDIT_20260513.md'
out.write_text('\n'.join(report), encoding='utf-8')
print(f'\n📄 보고서 저장: {out.name}', flush=True)

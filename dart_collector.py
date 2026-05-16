"""OpenDART 재무제표 수집기

금감원 DART API를 통해 분기/연간 재무제표를 수집하고
FnGuide 호환 parquet 캐시로 저장.

Usage:
    from dart_collector import DartCollector
    dc = DartCollector()
    df = dc.fetch_single('000660', 2020, 2024)
    dc.fetch_universe(tickers, 2020, 2024)
"""
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import urllib3

sys.stdout.reconfigure(encoding='utf-8')

try:
    import OpenDartReader
except ImportError:
    OpenDartReader = None

try:
    from config import DART_API_KEYS
except ImportError:
    DART_API_KEYS = None

try:
    from config import DART_API_KEY
except ImportError:
    DART_API_KEY = None

PROJECT_ROOT = Path(__file__).parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'

# ── account_id → 시스템 계정명 매핑 (IFRS 표준코드) ──
ACCOUNT_ID_MAP = {
    'ifrs-full_Revenue': '매출액',
    'dart_RevenueFromSaleOfGoodsProduct': '매출액',
    # NOTE: 'dart_TotalSellingGeneralAdministrativeExpenses'는 판매비와관리비(비용)로 매출액 아님 — 매핑 제거 (2026-05-04)
    'ifrs-full_GrossProfit': '매출총이익',
    'dart_OperatingIncomeLoss': '영업이익',
    'ifrs-full_ProfitLossBeforeTax': '세전계속사업이익',
    'ifrs-full_ProfitLoss': '당기순이익',
    'ifrs-full_IncomeTaxExpenseContinuingOperations': '법인세비용',
    'ifrs-full_CashFlowsFromUsedInOperatingActivities': '영업활동으로인한현금흐름',
    'ifrs-full_Assets': '자산',
    'ifrs-full_Liabilities': '부채',
    'ifrs-full_CurrentAssets': '유동자산',
    'ifrs-full_CurrentLiabilities': '유동부채',
    'ifrs-full_NoncurrentAssets': '비유동자산',
    'ifrs-full_CashAndCashEquivalents': '현금및현금성자산',
    'ifrs-full_Equity': '자본',
    # 2018~2019 DART API 구형 접두사 (ifrs-full_ 대신 ifrs_)
    'ifrs_Revenue': '매출액',
    'ifrs_GrossProfit': '매출총이익',
    'ifrs_ProfitLossBeforeTax': '세전계속사업이익',
    'ifrs_ProfitLoss': '당기순이익',
    'ifrs_IncomeTaxExpenseContinuingOperations': '법인세비용',
    'ifrs_CashFlowsFromUsedInOperatingActivities': '영업활동으로인한현금흐름',
    'ifrs_Assets': '자산',
    'ifrs_Liabilities': '부채',
    'ifrs_CurrentAssets': '유동자산',
    'ifrs_CurrentLiabilities': '유동부채',
    'ifrs_NoncurrentAssets': '비유동자산',
    'ifrs_CashAndCashEquivalents': '현금및현금성자산',
    'ifrs_Equity': '자본',
    # 지배주주 귀속 (PER/PBR/ROE 정확 계산용)
    'ifrs-full_ProfitLossAttributableToOwnersOfParent': '지배주주당기순이익',
    'ifrs-full_EquityAttributableToOwnersOfParent': '지배주주자본',
    'ifrs_ProfitLossAttributableToOwnersOfParent': '지배주주당기순이익',
    'ifrs_EquityAttributableToOwnersOfParent': '지배주주자본',
}

# 손익/현금흐름 항목 (Q4 도출 대상 — flow items)
FLOW_ACCOUNTS = {
    '매출액', '매출총이익', '영업이익', '세전계속사업이익',
    '당기순이익', '법인세비용', '영업활동으로인한현금흐름',
    '지배주주당기순이익',
}

# 재무상태표 항목 (스냅샷 — Q4 도출 불필요)
STOCK_ACCOUNTS = {
    '자산', '부채', '유동자산', '유동부채',
    '비유동자산', '현금및현금성자산', '자본',
    '지배주주자본',
}

# 보고서 코드
REPORT_CODES = {
    'Q1': '11013',
    'H1': '11012',  # 반기 (Q2 단일값 포함)
    'Q3': '11014',
    'Y':  '11011',  # 사업보고서 (연간)
}

# 분기 → 기준일 매핑 (12월 결산 기준)
QUARTER_END = {
    'Q1': '-03-31',
    'H1': '-06-30',
    'Q3': '-09-30',
    'Y':  '-12-31',
}

UNIT_DIVISOR = 1e8  # 원 → 억원


class DartCollector:
    """OpenDART 재무제표 수집기 (듀얼 키 지원)"""

    def __init__(self, api_key=None, api_keys=None):
        if OpenDartReader is None:
            raise ImportError('pip install opendartreader')

        # 듀얼 키: api_keys 리스트 또는 config.DART_API_KEYS
        keys = api_keys or DART_API_KEYS or ([api_key or DART_API_KEY] if (api_key or DART_API_KEY) else None)
        if not keys:
            raise ValueError('DART_API_KEY 필요 (config.py 또는 인자)')

        self._keys = [k for k in keys if k]
        self._key_idx = 0
        self._per_key_limit = 19900  # 키당 20,000 한도에서 안전마진 100건
        self._per_key_counts = [0] * len(self._keys)
        self.dart = OpenDartReader(self._keys[0])
        self._call_count = 0
        self._total_limit = self._per_key_limit * len(self._keys)
        print(f'  DART API 키 {len(self._keys)}개 (일일 총 {self._total_limit:,}건)')

    def _api_call(self, *args, **kwargs):
        """rate-limited API 호출 (키 자동 전환)"""
        if self._call_count >= self._total_limit:
            raise RuntimeError(f'전체 일일 한도 도달 ({self._call_count}건)')

        # 현재 키 한도 도달 시 다음 키로 전환
        if self._per_key_counts[self._key_idx] >= self._per_key_limit:
            next_idx = self._key_idx + 1
            if next_idx >= len(self._keys):
                raise RuntimeError(f'모든 키 한도 도달 ({self._call_count}건)')
            self._key_idx = next_idx
            self.dart = OpenDartReader(self._keys[next_idx])
            print(f'\n  키 전환: #{next_idx + 1} (이전 키 {self._per_key_counts[next_idx - 1]}건 사용)')

        time.sleep(0.15)
        self._per_key_counts[self._key_idx] += 1
        self._call_count += 1
        return self.dart.finstate_all(*args, **kwargs)

    def _parse_amount(self, val):
        """DART 금액 문자열 → float (억원)"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        if isinstance(val, (int, float)):
            return val / UNIT_DIVISOR
        s = str(val).strip().replace(',', '')
        if not s or s == '' or s == '-':
            return None
        try:
            return int(s) / UNIT_DIVISOR
        except ValueError:
            return None

    def _extract_accounts(self, df):
        """DataFrame에서 14개 타겟 계정만 추출 → dict {계정명: 값}"""
        if df is None or (hasattr(df, 'empty') and df.empty):
            return {}

        # 외화 재무제표 처리: USD → KRW 환율 변환, 기타 통화 제외
        fx_rate = 1.0
        if 'currency' in df.columns:
            currencies = df['currency'].dropna().unique()
            if len(currencies) == 1 and currencies[0] == 'USD':
                # USD 단일 통화 → 환율 변환
                fx_rate = self._get_usd_krw_rate(df)
            elif 'KRW' not in currencies:
                # KRW도 USD도 아닌 통화만 → 스킵
                return {}
            else:
                # KRW 행만 사용
                df = df[df['currency'].fillna('KRW') == 'KRW']
                if df.empty:
                    return {}

        result = {}
        for _, row in df.iterrows():
            aid = row.get('account_id', '')
            if aid in ACCOUNT_ID_MAP:
                sys_name = ACCOUNT_ID_MAP[aid]
                val = self._parse_amount(row.get('thstrm_amount'))
                if val is not None and sys_name not in result:
                    if fx_rate != 1.0:
                        val = val * fx_rate  # USD→KRW 변환 (이미 억원 단위)
                    result[sys_name] = val
        return result

    def _get_usd_krw_rate(self, df):
        """공시일 기준 USD/KRW 환율 조회 (yfinance 캐시)"""
        if not hasattr(self, '_fx_cache'):
            try:
                import yfinance as yf
                fx = yf.download('USDKRW=X', start='2018-01-01', period='max', progress=False)
                close = fx['Close'].iloc[:, 0] if isinstance(fx.columns, pd.MultiIndex) else fx['Close']
                self._fx_cache = close
            except Exception:
                self._fx_cache = None

        if self._fx_cache is None:
            return 1450.0  # 최근 평균 fallback

        # 공시접수일 추출
        rcept_no = str(df.iloc[0].get('rcept_no', ''))
        if len(rcept_no) >= 8:
            try:
                date = pd.Timestamp(rcept_no[:8])
                # 가장 가까운 거래일의 환율
                idx = self._fx_cache.index.searchsorted(date)
                idx = min(idx, len(self._fx_cache) - 1)
                return float(self._fx_cache.iloc[idx])
            except Exception:
                pass
        return 1450.0  # fallback

    def _extract_cumulative(self, df):
        """Q3 보고서에서 thstrm_add_amount (누적값) 추출"""
        if df is None or (hasattr(df, 'empty') and df.empty):
            return {}

        # USD 환율 처리 (extract_accounts와 동일)
        fx_rate = 1.0
        if 'currency' in df.columns:
            currencies = df['currency'].dropna().unique()
            if len(currencies) == 1 and currencies[0] == 'USD':
                fx_rate = self._get_usd_krw_rate(df)
            elif 'KRW' not in currencies:
                return {}
            else:
                df = df[df['currency'].fillna('KRW') == 'KRW']
                if df.empty:
                    return {}

        result = {}
        for _, row in df.iterrows():
            aid = row.get('account_id', '')
            if aid in ACCOUNT_ID_MAP:
                sys_name = ACCOUNT_ID_MAP[aid]
                val = self._parse_amount(row.get('thstrm_add_amount'))
                if val is not None and sys_name not in result:
                    if fx_rate != 1.0:
                        val = val * fx_rate
                    result[sys_name] = val
        return result

    def _get_rcept_dt(self, df):
        """보고서의 공시접수일 추출"""
        if df is None or (hasattr(df, 'empty') and df.empty):
            return None
        rcept = df.iloc[0].get('rcept_no', '')
        # rcept_no는 접수번호이지 날짜가 아님 — 별도 API 필요
        # 대신 rcept_no 앞 8자리가 날짜인 경우가 많음 (20250319...)
        if rcept and len(str(rcept)) >= 8:
            date_part = str(rcept)[:8]
            try:
                return pd.Timestamp(date_part)
            except Exception:
                pass
        return None

    # ── document API 폴백 (5/4, 5/15 분기 마감 직후 finstate_all 누락 우회) ──
    _DOC_TE_PAT = None  # lazy-compile

    @classmethod
    def _doc_pattern(cls):
        if cls._DOC_TE_PAT is None:
            import re as _re
            cls._DOC_TE_PAT = _re.compile(
                r'<TE ACODE="([^"]+)" ACONTEXT="([^"]+)"[^>]*ADECIMAL="(-?\d+)"[^>]*>([^<]*)</TE>'
            )
        return cls._DOC_TE_PAT

    @staticmethod
    def _parse_doc_value(val_str, adecimal):
        s = str(val_str).strip().replace(',', '').replace('(', '-').replace(')', '').replace(' ', '')
        if not s or s == '-':
            return None
        try:
            return float(s) * (10 ** -int(adecimal))
        except ValueError:
            return None

    def _parse_document_xml(self, doc_xml, member='Consolidated'):
        """document XML → {계정: 값} 추출. ACCOUNT_ID_MAP 14계정 + 영업CF dFQA.

        member: 'Consolidated' 또는 'Separate'
        반환: {계정: 값(원 단위)} — 분기단독(dFQQ) 또는 분기누적(dFQA) 또는 분기말 instant(eFQA)
        """
        import re as _re
        result = {}
        member_tag = f'{member}Member'
        pat_ctx = _re.compile(r'(CFY\d{4}[de](?:FQQ|FQA|FQ|SFQ|TFQ|SFA|TFA|FY|AFA))')
        for m in self._doc_pattern().finditer(doc_xml):
            code, ctx, dec, val = m.group(1), m.group(2), m.group(3), m.group(4)
            if code not in ACCOUNT_ID_MAP:
                continue
            if member_tag not in ctx:
                continue
            ctx_match = pat_ctx.match(ctx)
            if not ctx_match:
                continue
            ctx_base = ctx_match.group(1)
            # 1Q: dFQQ=dFQA. 손익은 dFQQ 우선, 영업CF는 dFQA, 재무상태표는 eFQA.
            # 첫 매칭 사용 (중복 시 무시) — XBRL 순서는 보고서마다 동일
            if 'dFQQ' not in ctx_base and 'eFQA' not in ctx_base and 'dFQA' not in ctx_base:
                continue
            v = self._parse_doc_value(val, dec)
            if v is None:
                continue
            sys_name = ACCOUNT_ID_MAP[code]
            if sys_name not in result:
                result[sys_name] = v
        return result

    def _fetch_quarter_via_document(self, ticker, year, rcode):
        """document API로 단일 분기 수집 (finstate_all 폴백용).

        흐름: dart.list로 year+rcode 매칭 rcept_no 찾기 → document XML → parse
        반환: ({계정: 값(억원)}, rcept_dt) 또는 ({}, None)
        """
        # rcode → 보고서명 매칭 (분기/반기/사업)
        rcode_to_kind = {
            '11013': '분기',  # Q1
            '11012': '반기',  # H1 (반기보고서)
            '11014': '분기',  # Q3 (분기보고서)
            '11011': '사업',  # Y (사업보고서)
        }
        kind_kw = rcode_to_kind.get(rcode)
        if not kind_kw:
            return {}, None

        # year의 보고서 (해당 종목 한정) — dart.list는 corp_code 기반
        try:
            time.sleep(0.15)
            self._per_key_counts[self._key_idx] += 1
            self._call_count += 1
            flist = self.dart.list(ticker, start=f'{year}-01-01', end=f'{year+1}-04-30',
                                    kind='A', final=True)
        except Exception:
            return {}, None
        if flist is None or len(flist) == 0:
            return {}, None

        # 분기/반기/사업보고서 + rcode 매칭
        # Q1 (11013): "분기보고서" + 3월말 기준
        # H1 (11012): "반기보고서"
        # Q3 (11014): "분기보고서" + 9월말 기준
        # Y (11011): "사업보고서"
        if kind_kw == '사업':
            cand = flist[flist['report_nm'].str.contains('사업보고서', na=False)]
            cand = cand[~cand['report_nm'].str.contains('첨부|위임', na=False)]
        elif kind_kw == '반기':
            cand = flist[flist['report_nm'].str.contains('반기보고서', na=False)]
        else:  # 분기
            cand = flist[flist['report_nm'].str.contains('분기보고서', na=False)]
        if len(cand) == 0:
            return {}, None

        # Q1 vs Q3 분기보고서 구분: rcept_no 날짜로 추정
        # Q1 = 4~5월 제출, Q3 = 10~11월 제출
        if rcode == '11013':  # Q1
            cand['_month'] = cand['rcept_no'].str[4:6].astype(int)
            cand = cand[cand['_month'].between(3, 7)]
        elif rcode == '11014':  # Q3
            cand['_month'] = cand['rcept_no'].str[4:6].astype(int)
            cand = cand[cand['_month'].between(9, 12)]
        if len(cand) == 0:
            return {}, None

        # 최신 정정 본 우선 (rcept_no 큰 것)
        cand = cand.sort_values('rcept_no', ascending=False)
        rno = cand.iloc[0]['rcept_no']
        rcept_dt = None
        try:
            rcept_dt = pd.Timestamp(str(rno)[:8])
        except Exception:
            pass

        # document API
        try:
            time.sleep(0.15)
            self._per_key_counts[self._key_idx] += 1
            self._call_count += 1
            doc_xml = self.dart.document(rno)
        except Exception:
            return {}, rcept_dt
        if not doc_xml or len(doc_xml) < 1000:
            return {}, rcept_dt

        # Consolidated 우선, 없으면 Separate
        accounts = self._parse_document_xml(doc_xml, 'Consolidated')
        if len(accounts) < 8:
            ofs_accounts = self._parse_document_xml(doc_xml, 'Separate')
            if len(ofs_accounts) > len(accounts):
                accounts = ofs_accounts

        # 원 → 억원 변환
        accounts = {k: v / UNIT_DIVISOR for k, v in accounts.items()}
        return accounts, rcept_dt

    def fetch_single(self, ticker, start_year, end_year):
        """단일 종목의 분기/연간 재무제표 수집

        Returns:
            DataFrame [계정, 기준일, 값, 종목코드, 공시구분, rcept_dt]
            or empty DataFrame if no data
        """
        rows = []

        # 분기별 fs_div 추적용 (진단/모니터링용 컬럼 저장)
        year_fs_divs = {}  # {(year, qname): 'CFS' or 'OFS'}

        for year in range(start_year, end_year + 1):
            year_data = {}  # {quarter: {계정: 값}}
            year_rcept = {}  # {quarter: rcept_dt}
            q3_cumulative = {}  # Q3 누적값 (Q4 도출용)

            for qname, rcode in REPORT_CODES.items():
                df = None
                used_fs_div = None
                try:
                    df = self._api_call(ticker, year, reprt_code=rcode, fs_div='CFS')
                    if df is not None and not (hasattr(df, 'empty') and df.empty):
                        used_fs_div = 'CFS'
                    else:
                        # CFS 없으면 OFS 폴백
                        df = self._api_call(ticker, year, reprt_code=rcode, fs_div='OFS')
                        if df is not None and not (hasattr(df, 'empty') and df.empty):
                            used_fs_div = 'OFS'
                except RuntimeError:
                    raise  # API 한도 에러는 상위로 전파
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        urllib3.exceptions.ProtocolError) as e:
                    # 네트워크 거부 = silent skip 금지. 상위로 전파해 호출자가 처리하도록
                    raise ConnectionError(f'DART API 연결 실패 ({ticker} {year} {rcode}): {type(e).__name__}') from e
                except Exception:
                    continue

                if df is None or (hasattr(df, 'empty') and df.empty):
                    # document API 폴백 (최근 2년 데이터만, finstate_all 누락 우회)
                    # 5/4 SK매핑버그 / 5/15 분기마감 직후 SK하이닉스·메가스터디 케이스
                    current_year = pd.Timestamp.now().year
                    if year < current_year - 1:
                        continue
                    try:
                        doc_accounts, doc_rcept_dt = self._fetch_quarter_via_document(ticker, year, rcode)
                    except Exception:
                        continue
                    if not doc_accounts:
                        continue
                    year_data[qname] = doc_accounts
                    year_rcept[qname] = doc_rcept_dt
                    year_fs_divs[(year, qname)] = 'DOC'
                    if qname == 'Q3':
                        # Q3 누적값: dFQA 우선 사용 (parse_document_xml에서 이미 dFQA 포함)
                        # 분기단독(dFQQ)이 누적값이 아니지만 1Q=2Q-Q1=Q3-H1 이라 dFQA 누적 필요
                        # 추후 정밀화 — 일단 비워둠 (Q3에서 finstate_all 폴백 발동 시 Q4 도출 부정확 가능)
                        pass
                    continue

                accounts = self._extract_accounts(df)
                rcept_dt = self._get_rcept_dt(df)
                year_data[qname] = accounts
                year_rcept[qname] = rcept_dt
                year_fs_divs[(year, qname)] = used_fs_div

                # Q3 보고서에서 누적값 추출
                if qname == 'Q3':
                    q3_cumulative = self._extract_cumulative(df)

            # Q4 도출: 연간 - Q3 누적 (flow items만)
            if 'Y' in year_data and q3_cumulative:
                q4_data = {}
                for acct, y_val in year_data['Y'].items():
                    if acct in FLOW_ACCOUNTS and acct in q3_cumulative:
                        q4_val = y_val - q3_cumulative[acct]
                        q4_data[acct] = q4_val
                    elif acct in STOCK_ACCOUNTS:
                        # 재무상태표: 연간 = Q4 스냅샷
                        q4_data[acct] = y_val
                if q4_data:
                    year_data['Q4'] = q4_data
                    year_rcept['Q4'] = year_rcept.get('Y')

            # rows 생성
            for qname, accounts in year_data.items():
                if qname == 'Y':
                    disclosure = 'y'
                    base_date = pd.Timestamp(f'{year}{QUARTER_END["Y"]}')
                elif qname == 'Q4':
                    disclosure = 'q'
                    base_date = pd.Timestamp(f'{year}-12-31')
                elif qname == 'Q1':
                    disclosure = 'q'
                    base_date = pd.Timestamp(f'{year}-03-31')
                elif qname == 'H1':
                    disclosure = 'q'
                    base_date = pd.Timestamp(f'{year}-06-30')
                elif qname == 'Q3':
                    disclosure = 'q'
                    base_date = pd.Timestamp(f'{year}-09-30')
                else:
                    continue

                rcept_dt = year_rcept.get(qname)
                # fs_div 추적: Q4는 Y에서 도출되므로 Y의 fs_div 사용
                fs_div_used = year_fs_divs.get((year, qname)) or year_fs_divs.get((year, 'Y'))
                for acct, val in accounts.items():
                    rows.append({
                        '계정': acct,
                        '기준일': base_date,
                        '값': val,
                        '종목코드': ticker,
                        '공시구분': disclosure,
                        'rcept_dt': rcept_dt,
                        'fs_div': fs_div_used,
                    })

        if not rows:
            return pd.DataFrame(columns=['계정', '기준일', '값', '종목코드', '공시구분', 'rcept_dt', 'fs_div'])

        result = pd.DataFrame(rows)
        # 중복 제거 (같은 계정+기준일+공시구분)
        result = result.drop_duplicates(subset=['계정', '기준일', '공시구분'], keep='last')
        return result

    def save_cache(self, ticker, df):
        """parquet 캐시 저장 (기존 데이터와 병합)"""
        if df.empty:
            return
        out_path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
        if out_path.exists():
            try:
                existing = pd.read_parquet(out_path)
                df = pd.concat([existing, df], ignore_index=True)
                df = df.drop_duplicates(subset=['계정', '기준일', '공시구분'], keep='last')
            except Exception:
                pass  # 기존 파일 손상 시 새 데이터로 덮어쓰기
        df.to_parquet(out_path, index=False)

    def load_cache(self, ticker):
        """parquet 캐시 로드"""
        path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
        if path.exists():
            return pd.read_parquet(path)
        return None

    def _cache_covers_years(self, ticker, start_year, end_year):
        """캐시가 요청 연도 범위를 커버하는지 확인"""
        cached = self.load_cache(ticker)
        if cached is None or cached.empty:
            return False
        try:
            cached_years = set(cached['기준일'].dt.year.unique())
            requested_years = set(range(start_year, end_year + 1))
            return requested_years.issubset(cached_years)
        except Exception:
            return False

    def fetch_universe(self, tickers, start_year, end_year, skip_cached=True):
        """전체 유니버스 수집

        Args:
            tickers: 종목코드 리스트
            start_year, end_year: 수집 범위
            skip_cached: True면 이미 캐시된 종목의 해당 연도 범위 스킵
        """
        total = len(tickers)
        success = 0
        skipped = 0
        failed = []
        t0 = time.time()

        for i, ticker in enumerate(tickers):
            # 캐시 확인 (연도 범위까지 체크)
            if skip_cached and self._cache_covers_years(ticker, start_year, end_year):
                skipped += 1
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - t0
                    print(f'  [{i+1}/{total}] {success}수집 {skipped}스킵 '
                          f'{len(failed)}실패 | API {self._call_count}건 | {elapsed:.0f}초')
                continue

            try:
                df = self.fetch_single(ticker, start_year, end_year)
                if not df.empty:
                    self.save_cache(ticker, df)
                    success += 1
                else:
                    failed.append((ticker, 'empty'))
            except RuntimeError as e:
                if '한도' in str(e):
                    print(f'\n일일 한도 도달! {self._call_count}건')
                    print(f'  수집: {success}, 스킵: {skipped}, 실패: {len(failed)}')
                    print(f'  남은 종목: {total - i}개 → 내일 재실행')
                    break
                failed.append((ticker, str(e)))
            except Exception as e:
                failed.append((ticker, str(e)))

            if (i + 1) % 100 == 0:
                elapsed = time.time() - t0
                rate = elapsed / (i + 1 - skipped) if (i + 1 - skipped) > 0 else 0
                remaining = rate * (total - i - 1) / 60
                print(f'  [{i+1}/{total}] {success}수집 {skipped}스킵 '
                      f'{len(failed)}실패 | API {self._call_count}건 | '
                      f'{elapsed:.0f}초 | 남은 ~{remaining:.0f}분')

        elapsed = time.time() - t0
        print(f'\n수집 완료: {success}수집 {skipped}스킵 {len(failed)}실패 | '
              f'API {self._call_count}건 | {elapsed/60:.1f}분')

        if failed:
            print(f'\n실패 종목 (처음 10개):')
            for t, reason in failed[:10]:
                print(f'  {t}: {reason}')

        return success, skipped, failed


def cross_validate(ticker, verbose=True):
    """OpenDART vs FnGuide 교차검증"""
    dc = DartCollector()

    # DART 수집 (최근 2년)
    dart_df = dc.fetch_single(ticker, 2023, 2024)

    # FnGuide 캐시 로드
    fn_path = CACHE_DIR / f'fs_fnguide_{ticker}.parquet'
    if not fn_path.exists():
        print(f'FnGuide 캐시 없음: {ticker}')
        return

    fn_df = pd.read_parquet(fn_path)

    # 연간 데이터만 비교
    dart_y = dart_df[dart_df['공시구분'] == 'y']
    fn_y = fn_df[fn_df['공시구분'] == 'y']

    if verbose:
        print(f'\n=== 교차검증: {ticker} ===')
        print(f'{"계정":<20} {"기준일":<12} {"DART":>12} {"FnGuide":>12} {"비율":>8} {"판정":>6}')
        print('-' * 72)

    match = 0
    total = 0
    for _, d_row in dart_y.iterrows():
        acct = d_row['계정']
        date = d_row['기준일']
        d_val = d_row['값']

        fn_match = fn_y[(fn_y['계정'] == acct) & (fn_y['기준일'] == date)]
        if fn_match.empty:
            continue

        f_val = fn_match.iloc[0]['값']
        total += 1

        if f_val == 0 and d_val == 0:
            ratio = 1.0
        elif f_val == 0:
            ratio = float('inf')
        else:
            ratio = d_val / f_val

        ok = 0.95 <= ratio <= 1.05
        if ok:
            match += 1

        if verbose:
            verdict = 'OK' if ok else 'DIFF'
            date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
            print(f'{acct:<20} {date_str:<12} {d_val:>12,.0f} {f_val:>12,.0f} {ratio:>7.3f}x {verdict:>6}')

    if verbose and total > 0:
        print(f'\n일치: {match}/{total} ({match/total:.0%})')

    return match, total


if __name__ == '__main__':
    # A1-5: SK하이닉스 교차검증
    cross_validate('000660')

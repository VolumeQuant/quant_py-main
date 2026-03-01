"""
KRX 데이터 시스템 로그인 — pykrx 세션 인증

KRX가 2026-02-27부터 data.krx.co.kr API에 로그인 필수 정책을 적용.
pykrx의 requests 호출을 공유 세션으로 교체하여 인증 쿠키를 유지.

사용법:
    import krx_auth
    krx_auth.login()  # config.py 또는 환경변수에서 자격증명 로드
"""

import os
import time
import requests
from pykrx.website.comm import webio

_session = requests.Session()
_logged_in = False


def login(user_id: str = None, password: str = None) -> bool:
    """KRX data.krx.co.kr 로그인 + pykrx 세션 교체"""
    global _logged_in
    if _logged_in:
        return True

    # 자격증명 확인: 인자 > config.py > 환경변수
    if not user_id:
        try:
            from config import KRX_USER_ID, KRX_PASSWORD
            user_id, password = KRX_USER_ID, KRX_PASSWORD
        except (ImportError, AttributeError):
            user_id = os.environ.get('KRX_USER_ID', '')
            password = os.environ.get('KRX_PASSWORD', '')

    if not user_id or not password:
        print("[KRX 인증] 자격증명 없음 — 비인증 모드로 진행")
        return False

    # 세션 헤더 설정
    _session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'X-Requested-With': 'XMLHttpRequest',
    })

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # 세션 쿠키 획득
            init_resp = _session.get('https://data.krx.co.kr/', timeout=15)
            print(f"[KRX 인증] 초기 접속: HTTP {init_resp.status_code}, 쿠키: {list(_session.cookies.keys())}")

            # 로그인
            resp = _session.post(
                'https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd',
                data={'mbrId': user_id, 'pw': password},
                timeout=15,
            )
            print(f"[KRX 인증] 로그인 응답: HTTP {resp.status_code}, 길이: {len(resp.text)}")

            if not resp.text.strip():
                print(f"[KRX 인증] 빈 응답 (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(3)
                    continue
                print("[KRX 인증] 로그인 실패 — 빈 응답 반복")
                return False

            result = resp.json()

            if result.get('_error_code') == 'CD001':
                _patch_pykrx()
                _logged_in = True
                print("[KRX 인증] 로그인 성공")
                return True
            else:
                msg = result.get('_error_message', str(result)[:200])
                print(f"[KRX 인증] 로그인 실패: {msg}")
                return False

        except requests.exceptions.JSONDecodeError:
            body_preview = resp.text[:200] if resp else '(no response)'
            print(f"[KRX 인증] JSON 파싱 실패 (attempt {attempt}/{max_retries}): {body_preview}")
            if attempt < max_retries:
                time.sleep(3)
                continue
        except Exception as e:
            print(f"[KRX 인증] 로그인 오류 (attempt {attempt}/{max_retries}): {type(e).__name__}: {e}")
            if attempt < max_retries:
                time.sleep(3)
                continue

    print("[KRX 인증] 로그인 최종 실패 — 비인증 모드로 진행")
    return False


def _patch_pykrx():
    """pykrx의 Post/Get을 공유 세션으로 교체"""

    def _post_read(self, **params):
        return _session.post(self.url, headers=self.headers, data=params)

    def _get_read(self, **params):
        return _session.get(self.url, headers=self.headers, params=params)

    webio.Post.read = _post_read
    webio.Get.read = _get_read

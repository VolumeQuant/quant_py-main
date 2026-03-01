"""
KRX 데이터 시스템 로그인 — pykrx 세션 인증

KRX가 2026-02-27부터 data.krx.co.kr API에 로그인 필수 정책을 적용.
pykrx의 requests 호출을 공유 세션으로 교체하여 인증 쿠키를 유지.

사용법:
    import krx_auth
    krx_auth.login()  # config.py 또는 환경변수에서 자격증명 로드
"""

import os
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd',
    })

    try:
        # 세션 쿠키 획득
        _session.get('https://data.krx.co.kr/', timeout=10)

        # 로그인
        resp = _session.post(
            'https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd',
            data={'mbrId': user_id, 'pw': password},
            timeout=10,
        )
        result = resp.json()

        if result.get('_error_code') == 'CD001':
            # pykrx 세션 교체
            _patch_pykrx()
            _logged_in = True
            print("[KRX 인증] 로그인 성공")
            return True
        else:
            print(f"[KRX 인증] 로그인 실패: {result.get('_error_message', 'unknown')}")
            return False

    except Exception as e:
        print(f"[KRX 인증] 로그인 오류: {type(e).__name__}: {e}")
        return False


def _patch_pykrx():
    """pykrx의 Post/Get을 공유 세션으로 교체"""

    def _post_read(self, **params):
        return _session.post(self.url, headers=self.headers, data=params)

    def _get_read(self, **params):
        return _session.get(self.url, headers=self.headers, params=params)

    webio.Post.read = _post_read
    webio.Get.read = _get_read

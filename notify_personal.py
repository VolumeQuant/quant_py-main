# -*- coding: utf-8 -*-
"""개인봇 보고 헬퍼. 사용: python notify_personal.py "메시지" 또는 stdin 파이프."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev')
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # 4096자 제한 분할
    for i in range(0, len(msg), 3900):
        chunk = msg[i:i+3900]
        r = requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': chunk}, timeout=20)
        if r.status_code != 200:
            print(f"[전송실패] {r.status_code}: {r.text[:200]}")
            return False
    print("[전송완료]")
    return True

if __name__ == '__main__':
    msg = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    send(msg)

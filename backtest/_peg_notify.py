# -*- coding: utf-8 -*-
"""개인봇 전송 헬퍼 — 채널 절대 안 건드림. 메시지는 인자(파일경로)로."""
import sys, requests
sys.path.insert(0, 'C:/dev')
import config

TOKEN = config.TELEGRAM_BOT_TOKEN
PRIVATE = config.TELEGRAM_PRIVATE_ID

def send(msg):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    # 4096 제한 → 분할
    chunks = []
    while msg:
        chunks.append(msg[:3900]); msg = msg[3900:]
    for c in chunks:
        r = requests.post(url, data={'chat_id': PRIVATE, 'text': c,
                                     'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=30)
        print('send:', r.status_code, r.json().get('ok'))
        if not r.json().get('ok'):
            print('  err:', r.json())

if __name__ == '__main__':
    path = sys.argv[1]
    with open(path, encoding='utf-8') as f:
        send(f.read())

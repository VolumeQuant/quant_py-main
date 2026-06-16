# -*- coding: utf-8 -*-
"""파일 내용을 개인봇으로 전송. usage: python _sp_notify.py <msgfile>  (plain text, no parse_mode)"""
import sys, requests
sys.path.insert(0, r'C:\dev')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
msg = open(sys.argv[1], encoding='utf-8').read()
r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
print(f'전송 status {r.status_code}, {len(msg)}자')
if r.status_code != 200: print(r.text[:300])

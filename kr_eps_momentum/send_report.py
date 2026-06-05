"""개인봇에 텍스트 보고서 전송 (stdlib만, GHA secrets 사용).
사용: python kr_eps_momentum/send_report.py <txt파일경로>
env: TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
"""
import os
import sys
import time
import urllib.request
import urllib.parse

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT = os.environ.get('TELEGRAM_PRIVATE_ID')
path = sys.argv[1] if len(sys.argv) > 1 else 'kr_eps_momentum/REPORT_FOR_USER.txt'

if not TOKEN or not CHAT:
    print('ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_PRIVATE_ID 미설정')
    sys.exit(1)

with open(path, encoding='utf-8') as f:
    text = f.read()

# 4096자 제한 → 3900자 단위로 줄바꿈 경계에서 분할
chunks, cur = [], ''
for line in text.split('\n'):
    if len(cur) + len(line) + 1 > 3900:
        if cur:
            chunks.append(cur)
        cur = line
    else:
        cur = (cur + '\n' + line) if cur else line
if cur:
    chunks.append(cur)

for i, ch in enumerate(chunks):
    data = urllib.parse.urlencode({
        'chat_id': CHAT,
        'text': ch,
        'disable_web_page_preview': 'true',
    }).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/sendMessage', data=data)
    resp = urllib.request.urlopen(req, timeout=20)
    print(f'sent chunk {i + 1}/{len(chunks)} (status={resp.status})')
    time.sleep(0.5)

print('REPORT_SENT_OK')

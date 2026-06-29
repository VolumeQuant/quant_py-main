# -*- coding: utf-8 -*-
import pandas as pd, os, io
f = 'data_cache/fs_dart_000660.parquet'
if not os.path.exists(f): f='data_cache/fs_dart_005930.parquet'
df = pd.read_parquet(f)
buf = io.StringIO()
buf.write('FILE %s\n' % f)
buf.write('COLS %r\n' % list(df.columns))
buf.write('GUBUN %r\n' % list(df['공시구분'].unique()))
q = df[df['공시구분']=='q']
buf.write('Q_ACCOUNTS %r\n' % sorted(q['계정'].astype(str).unique()))
buf.write('Q_DATES_n %d range %s %s\n' % (q['기준일'].nunique(), str(q['기준일'].min()), str(q['기준일'].max())))
op = q[q['계정']=='영업이익'].sort_values('기준일')[['기준일','값']]
buf.write('OP_TAIL\n%s\n' % op.tail(12).to_string())
open('C:/Users/user/AppData/Local/Temp/claude/C--dev-claude-code-quant-py-main/fd06d1ec-fd73-47e7-919e-175c79cb7dc2/scratchpad/out.txt','w',encoding='utf-8').write(buf.getvalue())

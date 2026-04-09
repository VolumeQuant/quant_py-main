"""공격 모드만 실행"""
import sys, os
sys.argv = ['', 'attack']
os.environ['V77_MODE'] = 'attack'
exec(open(os.path.join(os.path.dirname(__file__), 'v77_gsub_focused.py')).read())

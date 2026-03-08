#!/usr/bin/env python3
"""
API 서버 실행: 경로를 고정해서 반드시 이 프로젝트의 api.server 앱만 로드합니다.
다른 위치의 api 패키지 때문에 404가 나는 경우 이 스크립트로 실행하세요.

사용법:
  cd /Users/myno/Desktop/quant/trading-bot
  python3 run_api.py

엔진 연동(실시간 데이터):
  RUN_ENGINE=1 python3 run_api.py
"""
import logging
import os
import sys
from pathlib import Path

# 이 파일이 있는 디렉터리 = 프로젝트 루트 → sys.path 최우선
_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))
os.chdir(_root)

# 로그가 터미널에 보이도록 (Candle close, Paper: scheduling, Regime block 등)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)

# 위 설정 후에 앱을 import (문자열이 아닌 앱 객체로 uvicorn에 전달)
from api.server import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

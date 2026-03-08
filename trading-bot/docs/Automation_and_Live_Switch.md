# 완전 자동화 + Paper → Live 전환 가이드

Paper를 상시 실행하고, 승률·성과가 괜찮을 때만 Live로 전환하는 흐름을 위한 정리입니다.

---

## 1. 자동화 구성 요약

| 구성 요소 | 역할 |
|-----------|------|
| **Paper + API 프로세스** | 24/7 실행. WebSocket으로 1m 봉 수신 → 전략 → Paper 체결 → DB 저장 |
| **리서치 파이프라인 (cron)** | 주기적으로 동기화·데이터셋·아웃컴·스태빌리티·ML 재학습·리포트 |
| **모니터링** | API `/paper/performance`, `/today_summary` 로 승률·PnL 확인 |
| **Live 전환** | 설정만 바꾸고 프로세스 재시작 (수동 권장) |

---

## 2. Paper 24/7 실행

### 옵션 A: systemd (Linux 서버 권장)

프로젝트 루트를 `/opt/trading-bot` 이라고 가정:

```ini
# /etc/systemd/system/trading-bot-paper.service
[Unit]
Description=Trading Bot Paper + API
After=network.target mysql.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/trading-bot
Environment=DATABASE_URL=mysql+pymysql://...
ExecStart=/usr/bin/python3 main.py --mode paper --with-api
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot-paper
sudo systemctl start trading-bot-paper
sudo systemctl status trading-bot-paper
```

### 옵션 B: nohup (간단 테스트)

```bash
cd /path/to/trading-bot
nohup python3 main.py --mode paper --with-api > logs/paper.log 2>&1 &
```

### 옵션 C: screen / tmux

```bash
screen -S paper
cd /path/to/trading-bot
python3 main.py --mode paper --with-api
# Ctrl+A, D 로 detach. 재접속: screen -r paper
```

---

## 3. 리서치 파이프라인 주기 실행 (cron)

데이터 동기화·데이터셋·아웃컴·스태빌리티·ML 재학습을 매일 새벽 등에 한 번 돌리기:

```bash
# crontab -e
# 매일 04:00 (서버 시간 기준)
0 4 * * * cd /opt/trading-bot && PYTHONPATH=. python3 -m scheduler.research_pipeline >> /opt/trading-bot/logs/pipeline.log 2>&1
```

필요하면 `--skip-sync` 등으로 일부 단계만 실행하도록 조정.

---

## 4. Paper 성과 확인 (승률 / Live 전환 판단)

### API

- **최근 N일 Paper 성과**  
  `GET /paper/performance?days=7`  
  - `count`, `wins`, `losses`, `win_rate`, `pnl`, `avg_r` (평균 R)
- **오늘만**  
  `GET /today_summary`

예시 (7일):

```json
{
  "days": 7,
  "mode": "paper",
  "count": 42,
  "wins": 28,
  "losses": 14,
  "win_rate": 66.7,
  "pnl": 125.5,
  "avg_r": 0.18
}
```

### Live 전환 시 참고 기준 (예시)

- **거래 수**: 최소 30~50건 이상 쌓인 뒤 판단 (통계 의미 있도록)
- **승률**: 예) 55% 이상 유지
- **평균 R (avg_r)**: 예) 0.1 이상 (승자 규모가 패자보다 충분히 큼)
- **PnL**: Paper 기간 동안 누적이 플러스이고, 낙폭이 허용 범위 이내

위는 예시일 뿐이며, 본인 리스크 성향과 전략에 맞게 기준을 정하면 됩니다.

---

## 5. Live 전환 절차

### 5.1 사전 확인

- [ ] Paper로 충분한 기간(예: 1~4주) + 거래 수·승률·PnL 확인
- [ ] Binance Futures API 키 발급 (선택: IP 제한, 출금 비활성화 권장)
- [ ] Live 시 사용할 레버리지·포지션 크기 결정

### 5.2 설정 변경

1. **config/config.json**  
   `trading_mode` 를 `"live"` 로 변경:

   ```json
   "trading_mode": "live"
   ```

2. **환경 변수** (코드/설정 파일에 키 넣지 말 것):

   ```bash
   export BINANCE_API_KEY="your_key"
   export BINANCE_API_SECRET="your_secret"
   ```

   systemd 사용 시:

   ```ini
   [Service]
   Environment=BINANCE_API_KEY=...
   Environment=BINANCE_API_SECRET=...
   ```

   또는 `EnvironmentFile=/opt/trading-bot/.env` (`.env`는 .gitignore에 포함).

### 5.3 재시작

- systemd: `sudo systemctl restart trading-bot-paper`  
  (Live로 바뀌었어도 서비스 이름은 그대로 둬도 됨)
- nohup: 기존 프로세스 kill 후 `main.py --mode live --with-api` 다시 실행

### 5.4 Live 운용 시 주의

- 처음에는 **소액·낮은 레버리지**로 검증 후 점진적으로 조정
- `config.json` 의 `risk`, `capital_allocation`, `kelly` 등으로 1회 손실·총 노출 제한
- API 키는 **환경 변수만** 사용하고, 저장소/설정 파일에 커밋하지 않기

---

## 6. 한 페이지 체크리스트

| 단계 | 내용 |
|------|------|
| 1 | Paper + API 상시 실행 (systemd / nohup / screen) |
| 2 | cron으로 `scheduler.research_pipeline` 주기 실행 |
| 3 | `/paper/performance?days=7` 로 주기적으로 승률·PnL·avg_r 확인 |
| 4 | 기준 충족 시 `trading_mode`: `"live"`, API 키 환경변수 설정 후 프로세스 재시작 |
| 5 | Live는 소액·낮은 레버리지로 시작 후 점진적 조정 |

---

*문서 버전: 1.0. Paper 성과 API 및 자동화·Live 전환 절차 정리.*

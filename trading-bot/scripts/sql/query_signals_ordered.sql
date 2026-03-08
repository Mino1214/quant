-- candidate_signals + signal_outcomes 를 시간순으로 조회 (worker 병렬 삽입으로 id 순서가 뒤섞여 있어도 사용 시 정렬)
-- MySQL 등에서 직접 실행해서 확인/export 할 때 사용.

SELECT
  c.id AS candidate_id,
  COALESCE(c.`time`, c.`timestamp`) AS signal_time,
  c.symbol,
  c.side,
  c.regime,
  c.close AS entry_price,
  c.approval_score,
  c.ema_distance,
  c.volume_ratio,
  c.rsi AS rsi_5m,
  c.trade_outcome,
  c.blocked_reason,
  o.future_r_5,
  o.future_r_10,
  o.future_r_20,
  o.future_r_30,
  o.tp_hit_first,
  o.sl_hit_first,
  o.bars_to_outcome
FROM candidate_signals c
INNER JOIN signal_outcomes o ON o.candidate_signal_id = c.id
WHERE c.symbol = 'BTCUSDT'
ORDER BY COALESCE(c.`time`, c.`timestamp`) ASC, c.id ASC
LIMIT 100000;

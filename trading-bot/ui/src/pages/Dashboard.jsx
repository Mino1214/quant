import { useState, useEffect } from 'react';
import { getStatus, getPnlToday, getPosition, getConfig, getTodaySummary } from '../api/client';
import KPICard from '../components/KPICard';
import StatusBadge from '../components/StatusBadge';

export default function Dashboard() {
  const [status, setStatus] = useState({});
  const [pnl, setPnl] = useState(null);
  const [position, setPosition] = useState(null);
  const [config, setConfig] = useState(null);
  const [todaySummary, setTodaySummary] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [s, p, pos, c, summary] = await Promise.all([
          getStatus(),
          getPnlToday(),
          getPosition(),
          getConfig(),
          getTodaySummary(),
        ]);
        setStatus(s);
        setPnl(p?.pnl);
        setPosition(pos);
        setConfig(c);
        setTodaySummary(summary);
      } catch (e) {
        console.error(e);
      }
    };
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const st = status || {};
  const hasEngine = !!(st.engine_state || st.last_1m);
  const kpis = [
    { title: 'Trading Mode', value: (st.mode || '—').toString().toUpperCase(), variant: st.mode === 'live' ? 'short' : 'neutral' },
    { title: 'Bot Status', value: hasEngine ? 'Running' : '—', sub: hasEngine ? 'WebSocket 연결됨' : '엔진 미연동 (아래 실행 방법 참고)', variant: hasEngine ? 'long' : 'disabled' },
    { title: 'Symbol', value: st.symbol ?? '—' },
    { title: 'Today PnL', value: pnl != null ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} USDT` : '—', variant: pnl >= 0 ? 'long' : pnl != null ? 'short' : 'neutral' },
    { title: 'Open Position', value: position ? `${position.side} ${position.size}` : 'None', variant: position ? 'long' : 'disabled' },
    { title: 'Daily Limit', value: '정상', variant: 'long' },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>

      {!hasEngine && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
          <strong>전략 상태·차트 요약이 "—"인 이유</strong> API 서버가 엔진과 같은 프로세스로 떠 있지 않아서입니다. 아래처럼 <strong>한 번만</strong> 실행하세요 (9009 포트 사용 중이면 먼저 <code className="font-mono text-xs">lsof -i :9009</code> 후 <code className="font-mono text-xs">kill -9 &lt;PID&gt;</code>).
          <code className="block mt-2 font-mono text-xs bg-white/60 p-2 rounded whitespace-pre">
            {`cd /Users/myno/Desktop/quant/trading-bot\nRUN_ENGINE=1 python3 run_api.py`}
          </code>
          또는: <code className="font-mono text-xs">python3 main.py --mode paper --with-api</code> (반드시 trading-bot 폴더에서 실행)
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {kpis.map((k) => (
          <KPICard key={k.title} {...k} />
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="font-semibold text-gray-900 mb-3">실시간 차트 요약 (1m 데이터)</h2>
          <p className="text-sm text-gray-600">심볼: {st.symbol ?? '—'}</p>
          {st.last_ws_at && (
            <p className="text-xs text-green-700 mt-1">WS 수신: {st.last_ws_at?.slice(0, 19)} UTC · 이 시각이 갱신되면 1m 데이터가 들어오는 중</p>
          )}
          {st.current_1m && (
            <div className="mt-2 p-2 rounded bg-blue-50 border border-blue-100">
              <p className="text-xs font-medium text-blue-800">현재 진행 중 1m (실시간 갱신, UTC)</p>
              <p className="text-sm text-gray-800">O/H/L/C: {st.current_1m.open} / {st.current_1m.high} / {st.current_1m.low} / <strong>{st.current_1m.close}</strong>  V: {st.current_1m.volume}</p>
              <p className="text-xs text-gray-500">봉 시각: {st.current_1m.timestamp?.slice(0, 19)} UTC</p>
            </div>
          )}
          {st.last_1m && (
            <div className="mt-2 p-2 rounded bg-gray-50 border border-gray-100">
              <p className="text-xs font-medium text-gray-700">마지막 마감 1m (전략 사용 봉, UTC)</p>
              <p className="text-sm text-gray-800">O/H/L/C: {st.last_1m.open} / {st.last_1m.high} / {st.last_1m.low} / <strong>{st.last_1m.close}</strong>  V: {st.last_1m.volume}</p>
              <p className="text-xs text-gray-500">봉 시각: {st.last_1m.timestamp?.slice(0, 19)} UTC</p>
            </div>
          )}
          {!st.last_1m && !st.current_1m && (
            <p className="text-sm text-gray-500 mt-1">엔진 연동 시 표시 (RUN_ENGINE=1 python3 run_api.py)</p>
          )}
          <p className="text-xs text-gray-500 mt-2">모든 시각은 UTC. 한국 시간은 +9시간</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="font-semibold text-gray-900 mb-3">전략 상태</h2>
          <ul className="space-y-2 text-sm">
            <li className="flex justify-between">
              <span className="text-gray-600">15m Bias</span>
              <StatusBadge value={st.engine_state?.bias_15m ?? '—'} />
            </li>
            <li className="flex justify-between">
              <span className="text-gray-600">5m Trend</span>
              <StatusBadge value={st.engine_state?.trend_5m ?? '—'} />
            </li>
            <li className="flex justify-between">
              <span className="text-gray-600">1m Trigger</span>
              <StatusBadge value={st.engine_state?.trigger_1m ?? '—'} />
            </li>
            <li className="flex justify-between">
              <span className="text-gray-600">Regime</span>
              <StatusBadge value={st.engine_state?.regime ?? '—'} />
            </li>
            <li className="flex justify-between">
              <span className="text-gray-600">Regime Block</span>
              <span className="text-xs text-gray-600">{st.engine_state?.regime_blocked ?? '—'}</span>
            </li>
            <li className="flex justify-between border-t pt-2 mt-2">
              <span className="text-gray-600">마지막 진입 시각</span>
              <span className="text-xs text-green-700 font-medium">
                {st.engine_state?.last_order_at ? st.engine_state.last_order_at.slice(0, 19) + ' UTC' : '—'}
              </span>
            </li>
          </ul>
          {st.engine_state?.last_order_at && (
            <p className="text-xs text-green-600 mt-1">↑ 이 시각에 페이퍼 매매가 체결됨</p>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="font-semibold text-gray-900 mb-3">현재 포지션</h2>
          {position ? (
            <ul className="space-y-1 text-sm">
              <li>방향: <StatusBadge value={position.side} /></li>
              <li>진입가: {position.entry_price}</li>
              <li>손절가: {position.stop_loss ?? '—'}</li>
              <li>익절가: {position.take_profit ?? '—'}</li>
              <li>미실현 손익: {position.unrealized_pnl ?? '—'}</li>
            </ul>
          ) : (
            <p className="text-gray-500 text-sm">포지션 없음</p>
          )}
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="font-semibold text-gray-900 mb-3">오늘 거래 요약</h2>
          {(todaySummary && typeof todaySummary.count === 'number') ? (
            <>
              <p className="text-sm text-gray-600">총 거래 수: {todaySummary.count}</p>
              <p className="text-sm text-gray-600">승 / 패: {todaySummary.wins ?? 0} / {todaySummary.losses ?? 0}</p>
              <p className="text-sm text-gray-600">승률: {todaySummary.win_rate ?? 0}%</p>
              <p className="text-sm text-gray-600">오늘 PnL: <span className={(todaySummary.pnl ?? 0) >= 0 ? 'text-long' : 'text-short'}>{(todaySummary.pnl ?? 0) >= 0 ? '+' : ''}{(todaySummary.pnl ?? 0).toFixed(2)} USDT</span></p>
              <p className="text-sm text-gray-600">남은 거래 가능: {config?.risk?.max_trades_per_day != null ? Math.max(0, config.risk.max_trades_per_day - (todaySummary.count ?? 0)) : '—'}</p>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-600">총 거래 수: —</p>
              <p className="text-sm text-gray-600">승 / 패: —</p>
              <p className="text-sm text-gray-600">승률: —</p>
              <p className="text-sm text-gray-600">평균 손익: —</p>
              <p className="text-sm text-gray-600">남은 거래 가능 횟수: —</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect } from 'react';
import { getTradesRecent } from '../api/client';
import StatusBadge from '../components/StatusBadge';

function loadTrades(setTrades) {
  getTradesRecent(100).then((d) => setTrades(d.trades || [])).catch(console.error);
}

export default function Trades() {
  const [trades, setTrades] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    loadTrades(setTrades);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">거래 내역 / 로그</h1>

      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        <strong>페이퍼 트레이딩 / 백테스트 기록</strong>
        <p className="mt-1">
          페이퍼 모드에서 청산된 건, 백테스트에서 나온 건 모두 <strong>DB(trade_records)</strong>에 저장되며 이 목록에 표시됩니다.
          페이퍼는 청산이 발생할 때마다 자동 저장됩니다. 아래에서 Mode로 구분할 수 있습니다.
        </p>
        <button
          type="button"
          onClick={() => loadTrades(setTrades)}
          className="mt-2 px-3 py-1.5 bg-amber-200 hover:bg-amber-300 rounded text-sm font-medium"
        >
          새로고침
        </button>
      </div>

      <div className="flex gap-4 flex-wrap items-center">
        <span className="text-sm text-gray-600">Date range</span>
        <input type="date" className="rounded border border-gray-300 px-2 py-1 text-sm" />
        <span className="text-sm">~</span>
        <input type="date" className="rounded border border-gray-300 px-2 py-1 text-sm" />
        <select className="rounded border border-gray-300 px-2 py-1 text-sm">
          <option>전체 심볼</option>
        </select>
        <select className="rounded border border-gray-300 px-2 py-1 text-sm">
          <option>paper / live / backtest</option>
        </select>
        <button type="button" className="px-3 py-1 bg-neutral text-white rounded text-sm">필터</button>
      </div>

      <div className="flex gap-6">
        <div className={`flex-1 rounded-lg border border-gray-200 bg-white overflow-hidden ${selected ? 'max-w-[70%]' : ''}`}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">진입(Opened)</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">청산(Closed)</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Mode</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Entry</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Exit</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">PnL</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">PnL(R)</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {trades.length === 0 ? (
                  <tr><td colSpan={11} className="px-4 py-6 text-center text-gray-500 text-sm">거래 없음</td></tr>
                ) : (
                  trades.map((t, i) => (
                    <tr
                      key={i}
                      onClick={() => setSelected(t)}
                      className={`hover:bg-gray-50 cursor-pointer ${selected === t ? 'bg-blue-50' : ''}`}
                    >
                      <td className="px-4 py-2 text-sm">{i + 1}</td>
                      <td className="px-4 py-2 text-sm text-gray-700">{t.opened_at?.slice(0, 19) ?? '—'}</td>
                      <td className="px-4 py-2 text-sm text-gray-700">{t.closed_at?.slice(0, 19) ?? '—'}</td>
                      <td className="px-4 py-2 text-sm">
                        <span className={t.mode === 'paper' ? 'text-blue-600' : t.mode === 'backtest' ? 'text-gray-600' : 'text-red-600'}>
                          {t.mode || '—'}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-sm">{t.symbol}</td>
                      <td className="px-4 py-2"><StatusBadge value={t.side} /></td>
                      <td className="px-4 py-2 text-sm">{t.entry_price}</td>
                      <td className="px-4 py-2 text-sm">{t.exit_price}</td>
                      <td className={`px-4 py-2 text-sm font-medium ${(t.pnl ?? 0) >= 0 ? 'text-long' : 'text-short'}`}>{(t.pnl ?? 0).toFixed(2)}</td>
                      <td className="px-4 py-2 text-sm">{t.rr != null ? t.rr.toFixed(2) + 'R' : '—'}</td>
                      <td className="px-4 py-2 text-sm text-gray-600">{t.reason_exit ?? '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
        {selected && (
          <div className="w-80 rounded-lg border border-gray-200 bg-white p-4 flex-shrink-0">
            <h3 className="font-semibold text-gray-900 mb-3">거래 상세</h3>
            <ul className="text-sm space-y-1 text-gray-700">
              <li><strong>진입 시각:</strong> {selected.opened_at?.slice(0, 19) ?? '—'}</li>
              <li><strong>청산 시각:</strong> {selected.closed_at?.slice(0, 19) ?? '—'}</li>
              <li>Entry: {selected.entry_price} → Exit: {selected.exit_price}</li>
              <li>SL: {selected.stop_loss} TP: {selected.take_profit}</li>
              <li>Reason entry: {selected.reason_entry ?? '—'}</li>
              <li>Reason exit: {selected.reason_exit ?? '—'}</li>
            </ul>
            <p className="text-xs text-gray-500 mt-3">entry 시점 1m/5m/15m 조건, EMA, ATR, VMA 등은 백엔드 확장 시 표시</p>
          </div>
        )}
      </div>
    </div>
  );
}

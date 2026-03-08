import { useState, useEffect } from 'react';
import { getStatus, getPnlToday } from '../api/client';

export default function TopBar() {
  const [status, setStatus] = useState({ mode: '—', symbol: '—' });
  const [pnl, setPnl] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let t;
    const load = async () => {
      try {
        const [s, p] = await Promise.all([getStatus(), getPnlToday()]);
        setStatus(s);
        setPnl(p.pnl);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
      t = setTimeout(load, 10000);
    };
    load();
    return () => clearTimeout(t);
  }, []);

  const modeColor = status.mode === 'live' ? 'bg-red-600' : 'bg-blue-600';

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between gap-4">
      <div className="flex items-center gap-4">
        <span className={`px-2 py-1 rounded text-xs font-medium text-white ${modeColor}`}>
          {status.mode?.toUpperCase() || '—'}
        </span>
        <span className="text-sm text-gray-600">연결: {error ? '오류' : '정상'}</span>
        <span className="text-sm font-medium">{status.symbol || '—'}</span>
        {pnl != null && (
          <span className={`text-sm font-medium ${pnl >= 0 ? 'text-long' : 'text-short'}`}>
            오늘 손익: {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USDT
          </span>
        )}
      </div>
      <button
        type="button"
        className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700"
      >
        긴급 중지
      </button>
    </header>
  );
}

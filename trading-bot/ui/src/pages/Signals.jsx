import { useState, useEffect } from 'react';
import { getStatus, getSignalsRecent } from '../api/client';
import StatusBadge from '../components/StatusBadge';

export default function Signals() {
  const [status, setStatus] = useState({});
  const [signals, setSignals] = useState([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [s, d] = await Promise.all([getStatus(), getSignalsRecent(30)]);
        setStatus(s);
        setSignals(d.signals || []);
      } catch (e) {
        console.error(e);
      }
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">실시간 시그널 / 상태</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-semibold text-gray-900 mb-2">데이터 상태</h2>
        <ul className="text-sm text-gray-600 space-y-1">
          <li>현재 심볼: {status.symbol ?? '—'}</li>
          <li>최근 WebSocket 수신: —</li>
          <li>데이터 상태: 정상</li>
        </ul>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="font-semibold text-gray-900 mb-3">15분 상태</h3>
          <ul className="space-y-2 text-sm">
            <li>close &gt; EMA50 ? —</li>
            <li>EMA21 &gt; EMA50 ? —</li>
            <li>EMA50 slope pass ? —</li>
            <li className="pt-2">Bias Result: <StatusBadge value="—" /></li>
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="font-semibold text-gray-900 mb-3">5분 상태</h3>
          <ul className="space-y-2 text-sm">
            <li>EMA8 &gt; EMA21 &gt; EMA50 ? —</li>
            <li>close &gt; EMA21 ? —</li>
            <li className="pt-2">Trend Result: <StatusBadge value="—" /></li>
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="font-semibold text-gray-900 mb-3">1분 상태</h3>
          <ul className="space-y-2 text-sm">
            <li>low &lt;= EMA8 ? —</li>
            <li>close &gt; EMA8 ? —</li>
            <li>candle bullish ? —</li>
            <li>volume &gt; VMA ? —</li>
            <li className="pt-2">Trigger Result: <StatusBadge value="—" /></li>
          </ul>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <h2 className="font-semibold text-gray-900 p-4 border-b">최근 시그널 로그</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Bias</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Trend</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Trigger</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Final Signal</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Blocked Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {signals.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-500 text-sm">시그널 없음 (엔진 연동 시 표시)</td></tr>
              ) : (
                signals.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-sm">{row.time ?? '—'}</td>
                    <td className="px-4 py-2 text-sm">{row.symbol ?? '—'}</td>
                    <td className="px-4 py-2"><StatusBadge value={row.bias} /></td>
                    <td className="px-4 py-2"><StatusBadge value={row.trend} /></td>
                    <td className="px-4 py-2"><StatusBadge value={row.trigger} /></td>
                    <td className="px-4 py-2"><StatusBadge value={row.final_signal} /></td>
                    <td className="px-4 py-2 text-sm text-gray-600">{row.blocked_reason ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

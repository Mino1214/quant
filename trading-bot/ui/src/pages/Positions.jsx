import { useState, useEffect } from 'react';
import { getPosition } from '../api/client';
import StatusBadge from '../components/StatusBadge';

export default function Positions() {
  const [position, setPosition] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const p = await getPosition();
        setPosition(p);
      } catch (e) {
        setPosition(null);
      }
    };
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">포지션 / 주문 관리</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="font-semibold text-gray-900 mb-4">현재 포지션</h2>
        {position ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 text-sm">
              <p><span className="text-gray-600">Side</span> <StatusBadge value={position.side} /></p>
              <p><span className="text-gray-600">Quantity</span> {position.size}</p>
              <p><span className="text-gray-600">Entry Price</span> {position.entry_price}</p>
              <p><span className="text-gray-600">Mark Price</span> {position.mark_price ?? '—'}</p>
            </div>
            <div className="space-y-2 text-sm">
              <p><span className="text-gray-600">Stop Loss</span> {position.stop_loss ?? '—'}</p>
              <p><span className="text-gray-600">Take Profit</span> {position.take_profit ?? '—'}</p>
              <p><span className="text-gray-600">Unrealized PnL</span> {position.unrealized_pnl ?? '—'}</p>
              <p><span className="text-gray-600">Holding Time</span> —</p>
            </div>
            <div className="md:col-span-2 flex gap-2">
              <button type="button" className="px-4 py-2 bg-short text-white rounded text-sm font-medium hover:bg-red-700">Close Position</button>
              <button type="button" className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50">Move Stop to BE</button>
              <button type="button" className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50">Disable New Entries</button>
            </div>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">포지션 없음</p>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <h2 className="font-semibold text-gray-900 p-4 border-b">활성 주문</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Order Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Side</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Price</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Created At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-500 text-sm">활성 주문 없음</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-semibold text-gray-900 mb-2">브로커 상태</h2>
        <ul className="text-sm text-gray-600 space-y-1">
          <li>Exchange Connected: —</li>
          <li>API Key Loaded: —</li>
          <li>Precision Validated: —</li>
          <li>Margin Mode: —</li>
          <li>Leverage Applied: —</li>
        </ul>
      </div>
    </div>
  );
}

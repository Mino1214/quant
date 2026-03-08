import { useState } from 'react';
import { testDbConnection, testBinanceConnection } from '../api/client';

export default function Settings() {
  const [dbResult, setDbResult] = useState(null);
  const [binanceResult, setBinanceResult] = useState(null);

  const handleTestDb = async () => {
    setDbResult(null);
    try {
      const r = await testDbConnection();
      setDbResult(r.ok ? '연결 성공' : (r.error || '실패'));
    } catch (e) {
      setDbResult('오류: ' + e.message);
    }
  };

  const handleTestBinance = async () => {
    setBinanceResult(null);
    try {
      const r = await testBinanceConnection();
      setBinanceResult(r.ok ? '연결 성공' : (r.error || '실패'));
    } catch (e) {
      setBinanceResult('오류: ' + e.message);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">시스템 설정</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="font-semibold text-gray-900">연결 상태</h2>
        <ul className="text-sm text-gray-600 space-y-1">
          <li>DATABASE_URL: 환경변수 사용</li>
          <li>Binance API: 환경변수 사용</li>
          <li>WebSocket: 엔진 실행 시 연결</li>
        </ul>
        <div className="flex gap-3 flex-wrap">
          <button type="button" onClick={handleTestDb} className="px-4 py-2 bg-neutral text-white rounded text-sm font-medium hover:bg-blue-700">
            Test DB Connection
          </button>
          <button type="button" onClick={handleTestBinance} className="px-4 py-2 bg-neutral text-white rounded text-sm font-medium hover:bg-blue-700">
            Test Binance Connection
          </button>
          <button type="button" className="px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50">
            Reconnect WS
          </button>
        </div>
        {dbResult != null && <p className="text-sm">{dbResult}</p>}
        {binanceResult != null && <p className="text-sm">{binanceResult}</p>}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="font-semibold text-gray-900 mb-2">기타</h2>
        <ul className="text-sm text-gray-600 space-y-1">
          <li>Auto Reconnect: 사용</li>
          <li>Log Level: INFO</li>
          <li>Environment: dev</li>
          <li>Timezone: UTC</li>
        </ul>
        <button type="button" className="mt-4 px-4 py-2 border border-gray-300 rounded text-sm font-medium hover:bg-gray-50">
          Export Logs
        </button>
      </div>
    </div>
  );
}

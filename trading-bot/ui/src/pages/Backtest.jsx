import { useState, useEffect } from 'react';
import { getConfig } from '../api/client';
import StrategySectionCard from '../components/StrategySectionCard';

const PROJECT_ROOT = '/Users/myno/Desktop/quant/trading-bot';

function CopyButton({ text, label = '복사' }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="ml-2 px-2 py-1 text-xs rounded bg-gray-200 hover:bg-gray-300 text-gray-800"
    >
      {copied ? '복사됨' : label}
    </button>
  );
}

export default function Backtest() {
  const [config, setConfig] = useState(null);

  useEffect(() => {
    getConfig().then((c) => setConfig(c || {})).catch(() => setConfig({}));
  }, []);

  const cmdDb = `cd ${PROJECT_ROOT} && PYTHONPATH=. python3 main.py --mode backtest --from-db`;
  const cmdDbBars = `cd ${PROJECT_ROOT} && PYTHONPATH=. python3 main.py --mode backtest --from-db --bars 5000`;
  const cmdDbLimit = `cd ${PROJECT_ROOT} && PYTHONPATH=. python3 main.py --mode backtest --from-db --limit 5000`;
  const cmdCsv = `cd ${PROJECT_ROOT} && PYTHONPATH=. python3 main.py --mode backtest --data path/to/1m.csv`;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">백테스트</h1>

      <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <strong>사용 방법</strong>
        <ol className="list-decimal list-inside mt-2 space-y-1">
          <li><strong>Strategy</strong>에서 전략·리스크·Regime 파라미터를 조정한 뒤 <strong>Save Settings</strong>로 저장합니다.</li>
          <li>저장된 내용은 <code className="bg-white/70 px-1 rounded">config.json</code>에 기록되며, 이 설정이 백테스트 시 그대로 사용됩니다(스냅샷).</li>
          <li>아래 명령을 콘솔에서 실행하면, 현재 <code className="bg-white/70 px-1 rounded">config.json</code> 기준으로 백테스트가 돌아갑니다. 프로젝트 경로가 다르면 명령에서 <code className="bg-white/70 px-1 rounded">cd</code> 경로만 수정하세요.</li>
        </ol>
      </div>

      <StrategySectionCard
        title="DB로 백테스트 (btc1m 등)"
        description="MySQL btc1m 테이블에서 1m 봉을 읽어 백테스트합니다. DATABASE_URL 환경변수가 필요합니다."
      >
        <div className="space-y-2">
          <p className="text-xs text-gray-600">전체 데이터:</p>
          <div className="flex items-center flex-wrap gap-1">
            <code className="block flex-1 min-w-0 text-xs bg-gray-100 p-3 rounded font-mono break-all">
              {cmdDb}
            </code>
            <CopyButton text={cmdDb} />
          </div>
          <p className="text-xs text-gray-600 mt-3">기준(가장 최근 봉)으로부터 이전 N봉만 (권장):</p>
          <div className="flex items-center flex-wrap gap-1">
            <code className="block flex-1 min-w-0 text-xs bg-gray-100 p-3 rounded font-mono break-all">
              {cmdDbBars}
            </code>
            <CopyButton text={cmdDbBars} />
          </div>
          <p className="text-xs text-gray-600 mt-3">첫 봉(과거)부터 N개만: <code>--limit 5000</code></p>
          <div className="flex items-center flex-wrap gap-1">
            <code className="block flex-1 min-w-0 text-xs bg-gray-100 p-3 rounded font-mono break-all">
              {cmdDbLimit}
            </code>
            <CopyButton text={cmdDbLimit} />
          </div>
          <p className="text-xs text-gray-500 mt-2">테이블/심볼 변경: <code>--table btc1m --symbol BTCUSDT</code> (main.py에서 --symbol은 config 기준)</p>
        </div>
      </StrategySectionCard>

      <StrategySectionCard
        title="CSV로 백테스트"
        description="1m 봉 CSV 파일이 있을 때 사용. 컬럼: timestamp, open, high, low, close, volume"
      >
        <div className="flex items-center flex-wrap gap-1">
          <code className="block flex-1 min-w-0 text-xs bg-gray-100 p-3 rounded font-mono break-all">
            {cmdCsv}
          </code>
          <CopyButton text={cmdCsv} />
        </div>
        <p className="text-xs text-gray-500 mt-2">path/to/1m.csv 를 실제 CSV 경로로 바꾸세요.</p>
      </StrategySectionCard>

      <StrategySectionCard
        title="현재 백테스트에 사용될 설정 요약 (스냅샷)"
        description="Strategy에서 Save한 config.json 기준. 백테스트는 이 설정을 읽습니다."
      >
        {config && Object.keys(config).length > 0 ? (
          <pre className="text-xs bg-gray-50 p-3 rounded overflow-auto max-h-48">
            {JSON.stringify({ strategy: config.strategy, risk: config.risk, regime: config.regime, backtest: config.backtest, symbol: config.symbol }, null, 2)}
          </pre>
        ) : (
          <p className="text-sm text-gray-500">설정 불러오는 중이거나 API 미연결.</p>
        )}
      </StrategySectionCard>
    </div>
  );
}

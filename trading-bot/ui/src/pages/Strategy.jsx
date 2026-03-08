import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getConfig, saveConfig } from '../api/client';
import StrategySectionCard from '../components/StrategySectionCard';
import ConfirmLiveModal from '../components/ConfirmLiveModal';

const defaultConfig = {
  trading_mode: 'paper',
  symbol: 'BTCUSDT',
  regime: {
    enabled: true,
    ema_slow_len: 50,
    slope_lookback: 5,
    slope_threshold_pct: 0.02,
    adx_len: 14,
    adx_min: 14,
    atr_len: 14,
    natr_min: 0.05,
    natr_max: 1.2,
    score_threshold: 2,
  },
  strategy: { ema_fast: 8, ema_mid: 21, ema_slow: 50, slope_threshold: 0.0001, volume_ma_period: 20, volume_multiplier: 1.2, swing_lookback: 10 },
  risk: { risk_per_trade_pct: 0.5, atr_multiplier: 1.5, rr_target: 2.0, daily_loss_limit_r: -2, daily_profit_limit_r: 3, max_trades_per_day: 10, cooldown_bars: 1, atr_period: 14, swing_lookback: 10 },
  backtest: { initial_balance: 10000, commission_rate: 0.0004 },
};

function Field({ label, desc, value, onChange, type = 'number', min, max, step = 1 }) {
  const isNum = type === 'number';
  const displayValue = value != null && value !== '' ? value : '';
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      {desc && <p className="text-xs text-gray-500">{desc}</p>}
      <input
        type={type}
        value={displayValue}
        onChange={(e) => {
          const v = e.target.value;
          onChange(isNum ? (v === '' ? '' : Number(v)) : v);
        }}
        min={min}
        max={max}
        step={step}
        className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
      />
    </div>
  );
}

export default function Strategy() {
  const [config, setConfig] = useState(defaultConfig);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [liveModalOpen, setLiveModalOpen] = useState(false);

  useEffect(() => {
    getConfig().then((c) => {
      setConfig({
        ...defaultConfig,
        ...c,
        regime: { ...defaultConfig.regime, ...(c.regime || {}) },
        strategy: { ...defaultConfig.strategy, ...(c.strategy || {}) },
        risk: { ...defaultConfig.risk, ...(c.risk || {}) },
        backtest: { ...defaultConfig.backtest, ...(c.backtest || {}) },
      });
    }).catch(console.error);
  }, []);

  const update = (path, value) => {
    setConfig((prev) => {
      const next = JSON.parse(JSON.stringify(prev));
      const parts = path.split('.');
      let o = next;
      for (let i = 0; i < parts.length - 1; i++) o = o[parts[i]];
      o[parts[parts.length - 1]] = value;
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await saveConfig(config);
      setMessage('저장되었습니다.');
    } catch (e) {
      setMessage('저장 실패: ' + e.message);
    }
    setSaving(false);
  };

  const handleLiveConfirm = () => {
    update('trading_mode', 'live');
    setLiveModalOpen(false);
    handleSave();
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">전략 설정</h1>
      <p className="text-sm text-gray-600">
        저장한 설정은 <code className="bg-gray-100 px-1 rounded">config.json</code>에 기록되며, <Link to="/backtest" className="text-blue-600 hover:underline">백테스트</Link> 시 이 스냅샷이 사용됩니다. Backtest 화면에서 콘솔 실행 명령을 복사할 수 있습니다.
      </p>
      {message && <p className={`text-sm ${message.includes('실패') ? 'text-short' : 'text-long'}`}>{message}</p>}

      <StrategySectionCard
        title="Market Regime Filter (Score 방식)"
        description="ADX·Slope·NATR 각 +1점. score >= Score Threshold 이면 거래 허용. close vs EMA50으로 방향(TRENDING_UP/DOWN). 15m 기준."
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="regime_enabled"
              checked={config.regime?.enabled ?? true}
              onChange={(e) => update('regime.enabled', e.target.checked)}
              className="rounded border-gray-300"
            />
            <label htmlFor="regime_enabled" className="text-sm font-medium">Enable Market Regime Filter</label>
          </div>
          <p className="text-xs text-gray-500">Score: ADX≥최소 +1, |Slope|≥최소 +1, NATR≥최소 +1. 3개 중 2개 이상이면 통과(기본).</p>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Score Threshold" value={config.regime?.score_threshold} onChange={(v) => update('regime.score_threshold', v)} min={1} max={3} step={1} />
            <Field label="EMA Slow Length" value={config.regime?.ema_slow_len} onChange={(v) => update('regime.ema_slow_len', v)} min={20} max={200} />
            <Field label="Slope Lookback" value={config.regime?.slope_lookback} onChange={(v) => update('regime.slope_lookback', v)} min={1} max={20} />
            <Field label="Slope Threshold %" value={config.regime?.slope_threshold_pct} onChange={(v) => update('regime.slope_threshold_pct', v)} min={0.01} max={0.2} step={0.005} />
            <Field label="ADX Length" value={config.regime?.adx_len} onChange={(v) => update('regime.adx_len', v)} min={5} max={30} />
            <Field label="ADX Minimum" value={config.regime?.adx_min} onChange={(v) => update('regime.adx_min', v)} min={10} max={30} step={0.5} />
            <Field label="NATR Length" value={config.regime?.atr_len} onChange={(v) => update('regime.atr_len', v)} min={5} max={30} />
            <Field label="NATR Minimum" value={config.regime?.natr_min} onChange={(v) => update('regime.natr_min', v)} min={0.01} max={0.5} step={0.01} />
            <Field label="NATR Maximum" value={config.regime?.natr_max} onChange={(v) => update('regime.natr_max', v)} min={0.5} max={3} step={0.05} />
          </div>
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="기본 거래 설정" description="">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Symbol" type="text" value={config.symbol ?? ''} onChange={(v) => update('symbol', v)} />
          <div>
            <label className="block text-sm font-medium text-gray-700">Trading Mode</label>
            <div className="flex gap-2 mt-1">
              <button
                type="button"
                onClick={() => update('trading_mode', 'paper')}
                className={`px-3 py-2 rounded text-sm font-medium ${config.trading_mode === 'paper' ? 'bg-neutral text-white' : 'bg-gray-200'}`}
              >
                Paper
              </button>
              <button
                type="button"
                onClick={() => setLiveModalOpen(true)}
                className={`px-3 py-2 rounded text-sm font-medium ${config.trading_mode === 'live' ? 'bg-short text-white' : 'bg-gray-200'}`}
              >
                Live
              </button>
            </div>
          </div>
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="15분 시장 방향 필터" description="15분봉에서 롱/숏 가능 방향을 결정합니다.">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Bias EMA Mid" value={config.strategy?.ema_mid} onChange={(v) => update('strategy.ema_mid', v)} min={1} max={100} />
          <Field label="Bias EMA Slow" value={config.strategy?.ema_slow} onChange={(v) => update('strategy.ema_slow', v)} min={1} max={200} />
          <Field label="EMA50 Slope Threshold" value={config.strategy?.slope_threshold} onChange={(v) => update('strategy.slope_threshold', v)} step={0.0001} />
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="5분 추세 확인" description="5분봉 정렬 상태로 추세 방향 일치 여부를 판단합니다.">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="EMA Fast" value={config.strategy?.ema_fast} onChange={(v) => update('strategy.ema_fast', v)} min={1} max={50} />
          <Field label="EMA Mid" value={config.strategy?.ema_mid} onChange={(v) => update('strategy.ema_mid', v)} min={1} max={100} />
          <Field label="EMA Slow" value={config.strategy?.ema_slow} onChange={(v) => update('strategy.ema_slow', v)} min={1} max={200} />
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="1분 진입 트리거" description="1분봉 눌림/되돌림 후 재출발 봉만 진입합니다.">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Entry EMA Length" value={config.strategy?.ema_fast} onChange={(v) => update('strategy.ema_fast', v)} min={1} max={50} />
          <Field label="VMA Length" value={config.strategy?.volume_ma_period} onChange={(v) => update('strategy.volume_ma_period', v)} min={5} max={100} />
          <Field label="Volume Multiplier" value={config.strategy?.volume_multiplier} onChange={(v) => update('strategy.volume_multiplier', v)} min={0.5} max={3} step={0.1} />
          <Field label="Swing Lookback" value={config.strategy?.swing_lookback} onChange={(v) => update('strategy.swing_lookback', v)} min={3} max={50} />
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="손절 / 익절" description="손절은 Swing + ATR 혼합, 익절은 RR 기준입니다.">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="ATR Length" value={config.risk?.atr_period} onChange={(v) => update('risk.atr_period', v)} min={5} max={50} />
          <Field label="ATR Multiplier" value={config.risk?.atr_multiplier} onChange={(v) => update('risk.atr_multiplier', v)} min={0.5} max={5} step={0.1} />
          <Field label="RR Target" value={config.risk?.rr_target} onChange={(v) => update('risk.rr_target', v)} min={0.5} max={5} step={0.1} />
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="리스크 관리" description="">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Risk Per Trade (%)" value={config.risk?.risk_per_trade_pct} onChange={(v) => update('risk.risk_per_trade_pct', v)} min={0.1} max={5} step={0.1} />
          <Field label="Cooldown Bars" value={config.risk?.cooldown_bars} onChange={(v) => update('risk.cooldown_bars', v)} min={0} max={20} />
        </div>
      </StrategySectionCard>

      <StrategySectionCard title="일일 제한" description="">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Daily Loss Limit (R)" value={config.risk?.daily_loss_limit_r} onChange={(v) => update('risk.daily_loss_limit_r', v)} min={-10} max={0} step={0.5} />
          <Field label="Daily Profit Limit (R)" value={config.risk?.daily_profit_limit_r} onChange={(v) => update('risk.daily_profit_limit_r', v)} min={0} max={20} step={0.5} />
          <Field label="Max Trades Per Day" value={config.risk?.max_trades_per_day} onChange={(v) => update('risk.max_trades_per_day', v)} min={1} max={50} />
        </div>
      </StrategySectionCard>

      <div className="flex gap-3">
        <button type="button" onClick={handleSave} disabled={saving} className="px-4 py-2 bg-neutral text-white rounded font-medium hover:bg-blue-700 disabled:opacity-50">
          Save Settings
        </button>
        <button type="button" onClick={() => setConfig(defaultConfig)} className="px-4 py-2 border border-gray-300 rounded font-medium hover:bg-gray-50">
          Reset to Default
        </button>
        <button type="button" className="px-4 py-2 border border-gray-300 rounded font-medium hover:bg-gray-50">
          Test Config
        </button>
      </div>

      <ConfirmLiveModal open={liveModalOpen} onConfirm={handleLiveConfirm} onCancel={() => setLiveModalOpen(false)} />
    </div>
  );
}

import { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

/** Parse CSV text into array of objects. */
function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map((h) => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split(',').map((v) => v.trim());
    const row = {};
    headers.forEach((h, j) => {
      let val = values[j];
      if (val === '' || val == null) {
        row[h] = val;
        return;
      }
      const num = Number(val);
      row[h] = Number.isNaN(num) ? val : num;
    });
    rows.push(row);
  }
  return rows;
}

/** Edge decay: horizon vs avg_R, winrate */
function EdgeDecayChart({ data }) {
  const chartData = useMemo(
    () =>
      (data || [])
        .filter((r) => r.horizon != null)
        .map((r) => ({
          name: `${r.horizon}`,
          horizon: r.horizon,
          avg_R: typeof r.avg_R === 'number' ? r.avg_R : parseFloat(r.avg_R) || 0,
          winrate: typeof r.winrate === 'number' ? r.winrate : parseFloat(r.winrate) || 0,
          PF: typeof r.profit_factor === 'number' ? r.profit_factor : parseFloat(r.profit_factor) || 0,
        })),
    [data]
  );
  if (!chartData.length) return null;
  return (
    <div className="space-y-4">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="name" label={{ value: 'Horizon (bars)', position: 'insideBottom', offset: -5 }} />
          <YAxis yAxisId="left" tickFormatter={(v) => v.toFixed(3)} />
          <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => `${v}%`} />
          <Tooltip formatter={(v, name) => (name === 'winrate' ? `${Number(v).toFixed(1)}%` : Number(v).toFixed(4))} />
          <Legend />
          <Bar yAxisId="left" dataKey="avg_R" fill="#3b82f6" name="avg R" radius={[4, 4, 0, 0]} />
          <Bar yAxisId="right" dataKey="winrate" fill="#22c55e" name="Winrate %" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Parameter scan: top N by avg_R */
function ParameterScanChart({ data, topN = 12 }) {
  const chartData = useMemo(() => {
    if (!data || !data.length) return [];
    const key = 'avg_R';
    const sorted = [...data].sort((a, b) => (Number(b[key]) ?? 0) - (Number(a[key]) ?? 0)).slice(0, topN);
    return sorted.map((r, i) => ({
      name: `ema=${Number(r.ema_distance_threshold ?? 0).toFixed(4)} vol=${Number(r.volume_ratio_threshold ?? 0)} rsi=${r.rsi_threshold ?? '-'}`,
      short: `#${i + 1}`,
      avg_R: typeof r.avg_R === 'number' ? r.avg_R : parseFloat(r.avg_R) || 0,
      trades: r.trades ?? 0,
    }));
  }, [data, topN]);
  if (!chartData.length) return null;
  return (
    <ResponsiveContainer width="100%" height={360}>
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 5, right: 30, left: 80, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis type="number" tickFormatter={(v) => v.toFixed(3)} />
        <YAxis type="category" dataKey="short" width={70} tick={{ fontSize: 10 }} />
        <Tooltip
          content={({ payload }) => {
            if (!payload?.[0]) return null;
            const p = payload[0].payload;
            return (
              <div className="bg-white border border-gray-200 rounded shadow-lg p-2 text-xs">
                <p className="font-medium text-gray-800">{p.name}</p>
                <p>avg R: {Number(p.avg_R).toFixed(4)}</p>
                <p>trades: {p.trades}</p>
              </div>
            );
          }}
        />
        <Bar dataKey="avg_R" fill="#6366f1" name="avg R" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Regime comparison: one row per regime (from edge_decay by regime CSV) */
function RegimeChart({ data }) {
  const chartData = useMemo(() => {
    if (!data || !data.length) return [];
    return data.map((r) => ({
      name: `H${r.horizon}`,
      avg_R: typeof r.avg_R === 'number' ? r.avg_R : parseFloat(r.avg_R),
      trades: r.trades,
    }));
  }, [data]);
  if (!chartData.length) return null;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="name" />
        <YAxis tickFormatter={(v) => v.toFixed(3)} />
        <Tooltip formatter={(v) => Number(v).toFixed(4)} />
        <Bar dataKey="avg_R" fill="#8b5cf6" name="avg R" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Generic: first numeric column as bar, or small table */
function GenericChart({ data, filename }) {
  const chartData = useMemo(() => {
    if (!data || !data.length) return [];
    const keys = Object.keys(data[0]);
    const numKey = keys.find((k) => typeof data[0][k] === 'number');
    if (!numKey) return [];
    return data.slice(0, 20).map((r, i) => ({
      name: `${i + 1}`,
      [numKey]: r[numKey],
    }));
  }, [data]);
  if (!chartData.length) return null;
  const numKey = Object.keys(chartData[0] || {}).find((k) => k !== 'name');
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey={numKey} fill="#0ea5e9" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function CsvChartView({ csvText, filename }) {
  const data = useMemo(() => parseCsv(csvText || ''), [csvText]);
  const chartType = useMemo(() => {
    const lower = (filename || '').toLowerCase();
    if (lower.includes('edge_decay') && !lower.includes('trending') && !lower.includes('ranging'))
      return 'edge_decay';
    if (lower.includes('edge_decay') && (lower.includes('trending') || lower.includes('ranging')))
      return 'regime';
    if (lower.includes('parameter_scan')) return 'parameter';
    return 'generic';
  }, [filename]);

  if (!data.length) {
    return (
      <p className="text-sm text-gray-500">CSV를 파싱할 수 없거나 데이터가 없습니다.</p>
    );
  }

  return (
    <div className="space-y-4">
      {chartType === 'edge_decay' && <EdgeDecayChart data={data} />}
      {chartType === 'parameter' && <ParameterScanChart data={data} />}
      {chartType === 'regime' && <RegimeChart data={data} />}
      {chartType === 'generic' && <GenericChart data={data} filename={filename} />}
    </div>
  );
}

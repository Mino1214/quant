// 개발 시 기본으로 9009 직접 호출 (프록시 없이 동작). VITE_API_URL으로 변경 가능.
const raw = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:9009' : '');
const BASE = raw ? String(raw).replace(/\/+$/, '') : '/api';

function apiUrl(path) {
  const p = path.startsWith('/') ? path : '/' + path;
  return BASE === '/api' ? BASE + p : BASE + p;
}

async function safeJson(r) {
  const text = await r.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

export async function getHealth() {
  try {
    const r = await fetch(apiUrl('health'));
    return await safeJson(r);
  } catch {
    return { status: 'error' };
  }
}

const STATUS_FALLBACK = { mode: 'paper', symbol: '—', timestamp: null };

export async function getStatus() {
  try {
    const r = await fetch(apiUrl('status'));
    const data = await safeJson(r);
    if (!r.ok || !data || typeof data !== 'object') return { ...STATUS_FALLBACK };
    return { ...STATUS_FALLBACK, ...data };
  } catch {
    return { ...STATUS_FALLBACK };
  }
}

export async function getConfig() {
  try {
    const r = await fetch(apiUrl('config'));
    if (!r.ok) return null;
    return await safeJson(r);
  } catch {
    return null;
  }
}

export async function saveConfig(config) {
  const r = await fetch(apiUrl('config'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function reloadConfig() {
  const r = await fetch(apiUrl('config/reload'), { method: 'POST' });
  return r.json();
}

export async function getTradesRecent(limit = 50) {
  try {
    const r = await fetch(apiUrl('trades/recent?limit=' + limit));
    if (!r.ok) return { trades: [] };
    return await safeJson(r) || { trades: [] };
  } catch {
    return { trades: [] };
  }
}

export async function getPnlToday() {
  try {
    const r = await fetch(apiUrl('pnl/today'));
    if (!r.ok) return { pnl: 0, date: new Date().toISOString().slice(0, 10) };
    return await safeJson(r) || { pnl: 0 };
  } catch {
    return { pnl: 0, date: new Date().toISOString().slice(0, 10) };
  }
}

export async function getTodaySummary() {
  try {
    const r = await fetch(apiUrl('today_summary'));
    if (!r.ok) return { count: 0, wins: 0, losses: 0, win_rate: 0, pnl: 0 };
    return await safeJson(r) || { count: 0, wins: 0, losses: 0, win_rate: 0, pnl: 0 };
  } catch {
    return { count: 0, wins: 0, losses: 0, win_rate: 0, pnl: 0 };
  }
}

export async function getPosition() {
  try {
    const r = await fetch(apiUrl('position'));
    if (!r.ok) return null;
    const data = await safeJson(r);
    return data && typeof data === 'object' && 'side' in data ? data : null;
  } catch {
    return null;
  }
}

export async function getSignalsRecent(limit = 20) {
  try {
    const r = await fetch(apiUrl('signals/recent?limit=' + limit));
    if (!r.ok) return { signals: [] };
    return await safeJson(r) || { signals: [] };
  } catch {
    return { signals: [] };
  }
}

export async function testDbConnection() {
  try {
    const r = await fetch(apiUrl('config/test-db'), { method: 'POST' });
    const data = await safeJson(r);
    return data || { ok: false, error: 'No response' };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

export async function testBinanceConnection() {
  try {
    const r = await fetch(apiUrl('config/test-binance'), { method: 'POST' });
    const data = await safeJson(r);
    return data || { ok: false, error: 'No response' };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// --- Research ---
/** URL for a research output file. path can be "name" or "YYYYMMDDHHmm/name" for timestamped runs. */
export function researchOutputUrl(path) {
  const segments = (path || '').split('/').map((s) => encodeURIComponent(s)).join('/');
  return apiUrl('research/output/' + segments);
}

export async function getResearchOutputs() {
  try {
    const r = await fetch(apiUrl('research/outputs'));
    if (!r.ok) return { files: [] };
    return await safeJson(r) || { files: [] };
  } catch {
    return { files: [] };
  }
}

export async function runResearch(opts = {}) {
  const params = new URLSearchParams();
  if (opts.skip_sync !== undefined) params.set('skip_sync', opts.skip_sync);
  if (opts.skip_stability !== undefined) params.set('skip_stability', opts.skip_stability);
  if (opts.skip_walk_forward !== undefined) params.set('skip_walk_forward', opts.skip_walk_forward);
  if (opts.skip_ml !== undefined) params.set('skip_ml', opts.skip_ml);
  if (opts.skip_online_ml !== undefined) params.set('skip_online_ml', opts.skip_online_ml);
  const q = params.toString() ? '?' + params : '';
  const r = await fetch(apiUrl('research/run') + q, { method: 'POST' });
  return await safeJson(r) || { ok: false, error: 'No response' };
}

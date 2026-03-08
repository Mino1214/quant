export default function StatusBadge({ value }) {
  const v = (value || '').toUpperCase();
  const isLong = v === 'LONG' || v === 'PASS' || v === 'READY' || v === 'CONNECTED' || v === 'RUNNING';
  const isShort = v === 'SHORT' || v === 'FAIL' || v === 'ERROR' || v === 'LIVE';
  const isWait = v === 'WAITING' || v === 'WAIT' || v === 'WARNING';
  const isNone = v === 'NONE' || v === 'DISABLED' || !v;

  let cls = 'bg-neutral text-white';
  if (isLong) cls = 'bg-long text-white';
  else if (isShort) cls = 'bg-short text-white';
  else if (isWait) cls = 'bg-wait text-gray-900';
  else if (isNone) cls = 'bg-gray-200 text-gray-600';

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {value || '—'}
    </span>
  );
}

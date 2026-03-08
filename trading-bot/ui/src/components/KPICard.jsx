export default function KPICard({ title, value, sub, variant = 'neutral' }) {
  const colors = {
    long: 'border-l-long bg-green-50',
    short: 'border-l-short bg-red-50',
    wait: 'border-l-wait bg-yellow-50',
    neutral: 'border-l-neutral bg-blue-50',
    disabled: 'border-l-disabled bg-gray-50',
  };
  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 border-l-4 ${colors[variant] || colors.neutral}`}>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{title}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900">{value ?? '—'}</p>
      {sub != null && <p className="text-sm text-gray-600">{sub}</p>}
    </div>
  );
}

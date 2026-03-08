export default function StrategySectionCard({ title, description, children }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
        <h3 className="font-semibold text-gray-900">{title}</h3>
        {description && <p className="text-sm text-gray-600 mt-0.5">{description}</p>}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

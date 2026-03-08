import { useState } from 'react';

const CHECKLIST = [
  '실제 주문이 나간다는 것을 이해했습니다',
  'API 키와 권한을 확인했습니다',
  '손실 가능성을 이해했습니다',
];

export default function ConfirmLiveModal({ open, onConfirm, onCancel }) {
  const [checks, setChecks] = useState([false, false, false]);
  const [typed, setTyped] = useState('');

  const allChecked = checks.every(Boolean);
  const confirmed = typed.toUpperCase() === 'LIVE';

  const toggle = (i) => setChecks((c) => c.map((v, j) => (j === i ? !v : v)));
  const handleConfirm = () => {
    if (allChecked && confirmed) onConfirm();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        <h2 className="text-lg font-semibold text-gray-900">Live 모드 전환 확인</h2>
        <p className="mt-2 text-sm text-gray-600">
          실제 자금으로 주문이 체결됩니다. 아래 항목을 확인하고 동의한 경우에만 진행하세요.
        </p>
        <ul className="mt-4 space-y-2">
          {CHECKLIST.map((text, i) => (
            <li key={i} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={checks[i]}
                onChange={() => toggle(i)}
                className="rounded border-gray-300"
              />
              <span className="text-sm">{text}</span>
            </li>
          ))}
        </ul>
        <div className="mt-4">
          <label className="block text-sm font-medium text-gray-700">
            확인을 위해 <strong>LIVE</strong> 를 입력하세요
          </label>
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="LIVE"
            className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
        <div className="mt-6 flex gap-3 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 border border-gray-300 rounded text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!allChecked || !confirmed}
            className="px-4 py-2 bg-short text-white rounded text-sm font-medium hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Live 모드로 전환
          </button>
        </div>
      </div>
    </div>
  );
}

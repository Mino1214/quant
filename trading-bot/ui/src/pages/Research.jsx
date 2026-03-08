import { useState, useEffect } from 'react';
import { getResearchOutputs, runResearch, researchOutputUrl } from '../api/client';
import CsvChartView from '../components/CsvChartView';

const TYPE_LABEL = { image: '이미지', csv: 'CSV', json: 'JSON', text: '리포트', file: '파일' };

/** Group files by run (run id). Latest run first. */
function groupByRun(files) {
  const byRun = {};
  for (const f of files) {
    const run = f.run ?? '_root';
    if (!byRun[run]) byRun[run] = [];
    byRun[run].push(f);
  }
  const runs = Object.keys(byRun).sort((a, b) => {
    if (a === '_root') return 1;
    if (b === '_root') return -1;
    return b.localeCompare(a);
  });
  return { byRun, runs };
}

export default function Research() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [selected, setSelected] = useState(null);
  const [content, setContent] = useState(null);
  const [contentLoading, setContentLoading] = useState(false);

  const loadOutputs = async () => {
    const res = await getResearchOutputs();
    setFiles(res.files || []);
  };

  useEffect(() => {
    loadOutputs();
  }, []);

  const handleRunResearch = async () => {
    setRunResult(null);
    setLoading(true);
    try {
      const res = await runResearch({
        skip_sync: true,
        skip_stability: false,
        skip_walk_forward: true,
        skip_ml: false,
        skip_online_ml: true,
      });
      setRunResult(res);
      if (res.ok) await loadOutputs();
    } catch (e) {
      setRunResult({ ok: false, error: e.message });
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (f) => {
    setSelected(f);
    setContent(null);
    const path = f.path || f.name;
    if (f.type === 'image') {
      setContent({ type: 'image', url: researchOutputUrl(path) });
      return;
    }
    setContentLoading(true);
    try {
      const r = await fetch(researchOutputUrl(path));
      const text = await r.text();
      if (f.type === 'json') {
        try {
          setContent({ type: 'json', data: JSON.parse(text) });
        } catch {
          setContent({ type: 'text', text });
        }
      } else {
        setContent({ type: f.type, text });
      }
    } catch (e) {
      setContent({ type: 'error', text: e.message });
    } finally {
      setContentLoading(false);
    }
  };

  const { byRun, runs } = groupByRun(files);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">리서치</h1>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="font-semibold text-gray-900 mb-2">리서치 실행</h2>
        <p className="text-sm text-gray-600 mb-4">
          데이터셋·아웃컴·스태빌리티 스캔·ML 학습을 실행합니다. 완료 후 결과물을 아래에서 확인할 수 있습니다.
        </p>
        <button
          type="button"
          onClick={handleRunResearch}
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? '실행 중…' : '리서치 실행'}
        </button>
        {runResult && (
          <p className={`mt-3 text-sm ${runResult.ok ? 'text-green-600' : 'text-red-600'}`}>
            {runResult.ok ? runResult.message : (runResult.error || '실패')}
          </p>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="font-semibold text-gray-900 mb-4">결과물</h2>
        {files.length === 0 && (
          <p className="text-sm text-gray-500">결과 파일이 없습니다. 위에서 리서치를 실행하세요.</p>
        )}

        {runs.map((runId) => {
          const runFiles = byRun[runId];
          const images = runFiles.filter((f) => f.type === 'image');
          const csvs = runFiles.filter((f) => f.type === 'csv');
          const others = runFiles.filter((f) => f.type !== 'image' && f.type !== 'csv');
          const runLabel = runId === '_root' ? '기타' : runId;

          return (
            <div key={runId} className="mb-8 last:mb-0">
              <h3 className="text-base font-medium text-gray-800 mb-3 pb-2 border-b border-gray-200">
                Run: {runLabel}
              </h3>

              {(images.length > 0 || csvs.length > 0) && (
                <div className="mb-4">
                  <p className="text-sm text-gray-600 mb-2">차트 · CSV</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {images.map((f) => (
                      <div key={f.path} className="rounded-lg border border-gray-200 overflow-hidden bg-gray-50">
                        <button
                          type="button"
                          onClick={() => handleSelect(f)}
                          className="block w-full text-left"
                        >
                          <img
                            src={researchOutputUrl(f.path)}
                            alt={f.name}
                            className="w-full h-40 object-contain hover:opacity-90"
                          />
                          <p className="text-xs px-2 py-1 truncate text-gray-600" title={f.name}>
                            {f.name}
                          </p>
                        </button>
                      </div>
                    ))}
                    {csvs.map((f) => (
                      <div
                        key={f.path}
                        className={`rounded-lg border overflow-hidden ${
                          selected?.path === f.path ? 'border-indigo-400 bg-indigo-50' : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => handleSelect(f)}
                          className="block w-full text-left p-3 h-[120px] flex flex-col justify-end"
                        >
                          <span className="text-2xl text-gray-400 mb-1" aria-hidden>📊</span>
                          <p className="text-xs truncate text-gray-600 font-medium" title={f.name}>
                            {f.name}
                          </p>
                          <p className="text-xs text-gray-400">CSV → 차트로 보기</p>
                        </button>
                        <div className="flex border-t border-gray-200">
                          <a
                            href={researchOutputUrl(f.path)}
                            download={f.name}
                            onClick={(e) => e.stopPropagation()}
                            className="flex-1 text-center text-xs py-1.5 bg-gray-200 hover:bg-gray-300"
                          >
                            다운로드
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {(csvs.length > 0 || others.length > 0) && (
                <div className="flex flex-wrap gap-6">
                  {csvs.length > 0 && (
                    <div className="min-w-[200px]">
                      <p className="text-sm font-medium text-gray-700 mb-2">CSV 목록</p>
                      <ul className="space-y-1">
                        {csvs.map((f) => (
                          <li key={f.path} className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleSelect(f)}
                              className={`text-sm text-left flex-1 min-w-0 truncate px-2 py-1 rounded ${
                                selected?.path === f.path ? 'bg-indigo-100 text-indigo-800' : 'hover:bg-gray-100 text-gray-700'
                              }`}
                              title={f.name}
                            >
                              {f.name}
                            </button>
                            <a
                              href={researchOutputUrl(f.path)}
                              download={f.name}
                              className="text-xs px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded shrink-0"
                            >
                              다운로드
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {others.length > 0 && (
                    <div className="min-w-[200px]">
                      <p className="text-sm font-medium text-gray-700 mb-2">{TYPE_LABEL.file} / JSON / 리포트</p>
                      <ul className="space-y-1">
                        {others.map((f) => (
                          <li key={f.path}>
                            <button
                              type="button"
                              onClick={() => handleSelect(f)}
                              className={`text-sm text-left w-full truncate px-2 py-1 rounded ${
                                selected?.path === f.path ? 'bg-indigo-100 text-indigo-800' : 'hover:bg-gray-100 text-gray-700'
                              }`}
                              title={f.name}
                            >
                              {f.name}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        <div className="mt-6 border-t border-gray-200 pt-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">미리보기</h3>
          {contentLoading && <p className="text-sm text-gray-500">로딩 중…</p>}
          {!contentLoading && content && content.type === 'image' && (
            <img src={content.url} alt={selected?.name} className="max-w-full max-h-[70vh] rounded border border-gray-200" />
          )}
          {!contentLoading && content && content.type === 'json' && (
            <pre className="text-xs bg-gray-50 p-4 rounded overflow-auto max-h-[70vh]">
              {JSON.stringify(content.data, null, 2)}
            </pre>
          )}
          {!contentLoading && content && content.type === 'csv' && (
            <div className="space-y-4">
              <div className="rounded-lg border border-gray-200 bg-white p-4">
                <p className="text-sm font-medium text-gray-700 mb-3">차트</p>
                <CsvChartView csvText={content.text} filename={selected?.name} />
              </div>
              <details className="text-sm">
                <summary className="cursor-pointer text-gray-600 hover:text-gray-800">원문 CSV 보기</summary>
                <pre className="mt-2 text-xs bg-gray-50 p-4 rounded overflow-auto max-h-[50vh] whitespace-pre-wrap">
                  {content.text}
                </pre>
              </details>
            </div>
          )}
          {!contentLoading && content && content.type === 'text' && (
            <pre className="text-xs bg-gray-50 p-4 rounded overflow-auto max-h-[70vh] whitespace-pre-wrap">
              {content.text}
            </pre>
          )}
          {!contentLoading && content && content.type === 'error' && (
            <p className="text-sm text-red-600">{content.text}</p>
          )}
          {!contentLoading && !content && selected && (
            <p className="text-sm text-gray-500">파일을 선택하면 여기에 표시됩니다.</p>
          )}
          {!selected && !contentLoading && files.length > 0 && (
            <p className="text-sm text-gray-500">차트를 클릭하거나 CSV/파일을 선택하세요.</p>
          )}
        </div>
      </div>
    </div>
  );
}

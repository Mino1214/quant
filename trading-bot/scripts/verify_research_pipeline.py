#!/usr/bin/env python3
"""
11단계 Research Automation 검증 스크립트.
- research_pipeline 모듈 임포트 및 step 함수 존재 확인
- run_pipeline(모든 단계 스킵) 실행 시 리포트 파일 생성 확인
- (선택) python -m scheduler.research_pipeline --skip-* 실행
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_research_pipeline.py
"""
import sys
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def verify_pipeline_module():
    """스케줄러 파이프라인 단계·run_pipeline 존재."""
    from scheduler import research_pipeline

    for name in ["step_sync", "step_build_dataset", "step_outcomes", "step_stability", "step_walk_forward", "step_ml", "step_online_ml", "run_pipeline"]:
        assert hasattr(research_pipeline, name), "missing %s" % name
    print("[OK] research_pipeline has all step_* and run_pipeline")
    return True


def verify_run_pipeline_report():
    """모든 단계 스킵 후 run_pipeline 호출 시 리포트 파일 생성."""
    from scheduler.research_pipeline import run_pipeline

    out = tempfile.mkdtemp(prefix="verify_pipeline_")
    run_pipeline(
        symbol="BTCUSDT",
        output_dir=out,
        skip_sync=True,
        skip_build=True,
        skip_outcomes=True,
        skip_stability=True,
        skip_walk_forward=True,
        skip_ml=True,
        skip_online_ml=True,
    )
    # report_YYYYMMDD.txt
    prefix = "report_"
    reports = list(Path(out).glob(prefix + "*.txt"))
    assert len(reports) >= 1, "No report_*.txt in %s" % out
    content = reports[0].read_text()
    assert "Pipeline run at" in content or datetime.utcnow().strftime("%Y") in content or "run" in content.lower()
    print("[OK] run_pipeline (all skips) wrote report file")
    return True


def main():
    print("=== 11단계 Research Automation 검증 ===\n")
    ok = True
    for name, fn in [
        ("pipeline module", verify_pipeline_module),
        ("run_pipeline report", verify_run_pipeline_report),
    ]:
        try:
            fn()
        except Exception as e:
            print("[FAIL] %s: %s" % (name, e))
            ok = False
        print()
    if ok:
        print("11단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()

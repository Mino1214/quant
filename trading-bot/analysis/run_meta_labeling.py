"""
Phase 6 — Meta labeling: train binary (profitable/not) and expected_R models; output win_probability, expected_return, quality_score.

Trains logistic regression, random forest, gradient boosting on candidate features.
Outputs: meta_model_results.csv, feature_importance.csv, meta_model_summary.txt

Usage:
  python -m analysis.run_meta_labeling --from-db [--output-dir analysis/output]
  python -m analysis.run_meta_labeling --candidates-csv path/to/candidates.csv
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from analysis.store_loader import load_rows_from_store


def load_candidates_db(symbol: str = "BTCUSDT", limit: int = 10000, signals_table: str = "candidate_signals") -> list:
    """
    신규: feature_store_1m + outcome_store_1m에서 직접 로드 (가능하면).
    실패 시 기존 candidate_signals 경로 fallback.
    """
    try:
        rows = load_rows_from_store(symbol=symbol, limit=limit, feature_version=1)
        if rows:
            return rows
    except Exception:
        pass
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes

    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit, signals_table=signals_table)
    finally:
        db.close()


def load_candidates_csv(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def _flat_features(r: dict) -> dict:
    if "feature_values" in r and isinstance(r.get("feature_values"), dict):
        return {**r, **r["feature_values"]}
    return r


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta labeling: train LR, RF, GB on signal outcomes")
    parser.add_argument("--candidates-csv", type=str, default="")
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="DB signals table/view name (default: candidate_signals)")
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print("CSV not found:", path, file=sys.stderr)
            sys.exit(1)
        rows = load_candidates_csv(path)
        r_key = "R_return"
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit, signals_table=args.signals_table)
        r_key = "future_r_30"
    else:
        print("Provide --candidates-csv or --from-db", file=sys.stderr)
        sys.exit(1)

    if not rows or len(rows) < 50:
        print("Need at least 50 rows", file=sys.stderr)
        sys.exit(0)

    # Build feature matrix and targets
    feature_cols = ["ema_distance", "volume_ratio", "rsi", "rsi_5m", "momentum_ratio", "pullback_depth_pct", "upper_wick_ratio", "lower_wick_ratio", "ema50_slope", "breakout_confirmation"]
    X_list = []
    y_bin = []
    y_r = []
    for r in rows:
        flat = _flat_features(r)
        r_val = flat.get(r_key) or flat.get("future_r_30") or flat.get("R_return")
        if r_val is None or r_val == "":
            continue
        try:
            r_val = float(r_val)
        except (TypeError, ValueError):
            continue
        vec = []
        for c in feature_cols:
            v = flat.get(c)
            if v is None or v == "":
                vec.append(0.0)
            else:
                try:
                    vec.append(float(v))
                except (TypeError, ValueError):
                    vec.append(0.0)
        X_list.append(vec)
        y_bin.append(1 if r_val > 0 else 0)
        y_r.append(max(-20, min(20, r_val)))
    X = np.array(X_list)
    y_bin = np.array(y_bin)
    y_r = np.array(y_r)
    if len(X) < 30:
        print("Too few rows with valid R", file=sys.stderr)
        sys.exit(0)

    from sklearn.model_selection import train_test_split
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, RandomForestRegressor, GradientBoostingRegressor

    X_train, X_test, yb_train, yb_test, yr_train, yr_test = train_test_split(
        X, y_bin, y_r, test_size=0.2, random_state=42
    )

    model_results = []
    feature_importance_rows = []

    # Logistic regression
    lr_clf = LogisticRegression(max_iter=500, random_state=42)
    lr_clf.fit(X_train, yb_train)
    acc_lr = (lr_clf.predict(X_test) == yb_test).mean()
    model_results.append({"model": "logistic_regression", "accuracy": round(acc_lr, 4), "target": "binary"})
    coef = lr_clf.coef_[0]
    for i, c in enumerate(feature_cols):
        feature_importance_rows.append({"model": "logistic_regression", "feature": c, "importance": round(float(coef[i]), 6)})

    # Random forest
    rf_clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    rf_clf.fit(X_train, yb_train)
    acc_rf = (rf_clf.predict(X_test) == yb_test).mean()
    model_results.append({"model": "random_forest", "accuracy": round(acc_rf, 4), "target": "binary"})
    for i, c in enumerate(feature_cols):
        feature_importance_rows.append({"model": "random_forest", "feature": c, "importance": round(float(rf_clf.feature_importances_[i]), 6)})

    # Gradient boosting
    gb_clf = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
    gb_clf.fit(X_train, yb_train)
    acc_gb = (gb_clf.predict(X_test) == yb_test).mean()
    model_results.append({"model": "gradient_boosting", "accuracy": round(acc_gb, 4), "target": "binary"})
    for i, c in enumerate(feature_cols):
        feature_importance_rows.append({"model": "gradient_boosting", "feature": c, "importance": round(float(gb_clf.feature_importances_[i]), 6)})

    # Regressors for expected_R (RF only for importance)
    rf_reg = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
    rf_reg.fit(X_train, yr_train)
    mse = ((rf_reg.predict(X_test) - yr_test) ** 2).mean()
    model_results.append({"model": "random_forest_regressor", "mse": round(mse, 6), "target": "expected_R"})

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "meta_model_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["model", "accuracy", "mse", "target"])
        w.writeheader()
        for r in model_results:
            row = {"model": r["model"], "accuracy": r.get("accuracy", ""), "mse": r.get("mse", ""), "target": r.get("target", "")}
            w.writerow(row)
    print(f"Wrote {out_dir / 'meta_model_results.csv'}")

    with open(out_dir / "feature_importance.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["model", "feature", "importance"])
        w.writeheader()
        w.writerows(feature_importance_rows)
    print(f"Wrote {out_dir / 'feature_importance.csv'}")

    lines = [
        "Meta labeling model summary",
        "=" * 50,
        f"Train size: {len(X_train)}, Test size: {len(X_test)}",
        "",
        "Binary (win) accuracy:",
    ]
    for r in model_results:
        if r.get("target") == "binary":
            lines.append(f"  {r['model']}: {r.get('accuracy', 0):.4f}")
    lines.append("")
    lines.append("Expected R regressor MSE (RF):")
    for r in model_results:
        if r.get("target") == "expected_R":
            lines.append(f"  {r['model']}: MSE = {r.get('mse', 0)}")
    (out_dir / "meta_model_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'meta_model_summary.txt'}")


if __name__ == "__main__":
    main()

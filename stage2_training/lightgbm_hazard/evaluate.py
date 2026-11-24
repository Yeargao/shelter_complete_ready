"""Evaluate an already-trained LightGBM discrete-time competing-risks model.
No Optuna calls; never writes best_models.pkl.
Run from project root: python lightgbm_hazard/evaluate.py
"""
import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.metrics import censor_km, cause_cindex, brier_cif, calibration_cif
from lightgbm_hazard.train import predict


def write_csv_safely(df, target):
    """Write a fresh version; do not overwrite a locked or existing CSV."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d_%H%M%S}{target.suffix}")
    df.to_csv(target, index=False)
    return str(target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=str(ROOT/'outputs/lightgbm_hazard/best_models.pkl'))
    ap.add_argument('--input', default=str(ROOT/'inputs/lightgbm_hazard.csv'))
    ap.add_argument('--output', default=str(ROOT/'outputs/lightgbm_hazard'))
    args = ap.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    # WARNING: unpickle only your own trusted model file.
    with open(args.model, 'rb') as f:
        bundle = pickle.load(f)
    models = bundle['models']
    categories = bundle['categories']
    max_day = int(bundle['max_day'])
    if not models:
        raise ValueError('Saved model contains no cause-specific classifiers.')

    df = pd.read_csv(args.input)
    df['duration_days'] = pd.to_numeric(df.duration_days, errors='coerce').fillna(1).clip(lower=1).astype(int)
    train = df[df.split == 'train'].reset_index(drop=True)
    test = df[df.split == 'test'].reset_index(drop=True)
    if train.empty or test.empty:
        raise ValueError('Expected nonempty train and test splits in input CSV.')

    cif, _ = predict(models, categories, test, max_day)
    km = censor_km(train.duration_days, train.event_observed)
    records, calibration = [], []
    for cause, arr in cif.items():
        record = {
            'cause': cause,
            'cause_specific_c_index': cause_cindex(
                test.duration_days, test.event_type, cause, arr[:, -1]
            ),
        }
        bs = []
        for horizon in (7, 30, 60, 90, 180):
            if horizon > max_day:
                continue
            value = brier_cif(
                test.duration_days, test.event_type, test.event_observed,
                cause, arr[:, horizon-1], horizon, km
            )
            record[f'brier_{horizon}d'] = value
            bs.append((horizon, value))
            for idx, row in enumerate(calibration_cif(
                test.duration_days, test.event_type, test.event_observed,
                cause, arr[:, horizon-1], horizon, km
            )):
                calibration.append(dict(cause=cause, horizon=horizon, bin=idx+1, **row))
        record['integrated_brier_score'] = (
            float(np.trapezoid([v for _, v in bs], [h for h, _ in bs]) / (bs[-1][0]-bs[0][0]))
            if len(bs) > 1 else None
        )
        records.append(record)

    metrics_path = write_csv_safely(pd.DataFrame(records), output/'metrics_by_cause.csv')
    calibration_path = write_csv_safely(pd.DataFrame(calibration), output/'calibration.csv')
    summary = {
        'evaluation_only': True,
        'model_file': str(Path(args.model).resolve()),
        'max_day': max_day,
        'test_size': len(test),
        'causes': list(models),
        'metrics_by_cause_file': metrics_path,
        'calibration_file': calibration_path,
        'notes': (
            'IBS uses trapezoidal integration over available evaluation horizons '
            '(7,30,60,90,180 up to max_day), not a daily-grid IBS. '
            'C-index is calculated at the last modeled day. '
            'Uses original common.metrics functions.'
        )
    }
    summary_path = output/f'evaluation_summary_{datetime.now():%Y%m%d_%H%M%S}.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Apply saved model to a full race CSV and write predictions for every runner.

Usage:
    python tools/apply_model_to_full.py --input results/backtest_full.csv --out results/backtest_full_pred.csv
"""
import os
import sys
import argparse
import joblib
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MODEL_PATH = 'models/prediction_model.pkl'


def load_model(path: str):
    payload = joblib.load(path)
    if isinstance(payload, dict):
        model = payload['model']
        features = payload.get('features', None)
    else:
        model = payload
        features = None
    return model, features


def predict_df(model, features, df: pd.DataFrame):
    df = df.copy()
    if features is None:
        # try to infer numeric columns except some known columns
        features = [c for c in df.columns if c not in ('race_id','race_title','horse_name','odds','actual_pos','finishing_position','hit','pnl')]
    for col in features:
        if col not in df.columns:
            df[col] = 0.0
    X = df[features].copy()
    for col in features:
        X[col] = pd.to_numeric(X[col], errors='coerce').fillna(0.0)
    try:
        proba = model.predict_proba(X.values)[:,1]
    except Exception:
        n = len(df)
        proba = np.full(n, 1.0 / n)
    df['pred_prob'] = np.round(proba, 4)
    odds_num = pd.to_numeric(df['odds'], errors='coerce')
    df['expected_value'] = np.round(df['pred_prob'] * odds_num, 3)
    return df


def main(input_csv: str, out_csv: str, model_path: str = MODEL_PATH):
    model, features = load_model(model_path)
    df = pd.read_csv(input_csv)
    df2 = predict_df(model, features, df)
    df2.to_csv(out_csv, index=False)
    print('Wrote', out_csv)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='results/backtest_full.csv')
    parser.add_argument('--out', default='results/backtest_full_pred.csv')
    parser.add_argument('--model', default=MODEL_PATH)
    args = parser.parse_args()
    main(args.input, args.out, args.model)

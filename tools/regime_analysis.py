"""Regime analysis tool: computes per-race metrics, assigns regimes, and reports regime-specific ROI, ECE, uncertainty, and transitions.

Usage:
    python tools/regime_analysis.py --input results/backtest_full.csv --out reports/regimes
"""
import os
import sys
import argparse
import numpy as np
import pandas as pd

# ensure project root is on sys.path for local imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.market.advanced_regime_detector import AdvancedRegimeDetector
from core.market.regime_metrics import batch_compute_metrics
from core.market.regime_survival_metrics import RegimeSurvivalMetrics
from core.market.regime_transition_tracker import RegimeTransitionTracker


def compute_ece(y_true, y_prob, n_bins=10):
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi)
        if not mask.any():
            continue
        acc = y_true[mask].mean()
        conf = y_prob[mask].mean()
        ece += (mask.sum() / len(y_prob)) * abs(acc - conf)
    return float(ece)


def main(input_csv: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    df = pd.read_csv(input_csv)

    # required: race_id per runner
    if 'race_id' not in df.columns:
        raise RuntimeError('results CSV must contain race_id column')

    # compute per-race metrics
    prob_col = 'pred_prob' if 'pred_prob' in df.columns else ('probability' if 'probability' in df.columns else 'implied_prob')
    metrics_df = batch_compute_metrics(
        df,
        race_id_col='race_id',
        odds_col='odds',
        prob_col=prob_col,
        uncertainty_col='model_uncertainty' if 'model_uncertainty' in df.columns else 'uncertainty_score',
        edge_col='edge' if 'edge' in df.columns else 'expected_value',
        hit_col='hit' if 'hit' in df.columns else 'actual_hit',
        profit_col='pnl' if 'pnl' in df.columns else 'profit',
        stake_col='stake' if 'stake' in df.columns else 'bet_size',
    ).reset_index()

    race_order = list(dict.fromkeys(df['race_id'].tolist()))
    metrics_df['__order__'] = metrics_df['race_id'].map({race_id: index for index, race_id in enumerate(race_order)})
    metrics_df = metrics_df.sort_values('__order__').reset_index(drop=True)

    detector = AdvancedRegimeDetector(window_size=min(20, max(5, len(metrics_df))))
    detected = detector.detect_series(metrics_df, order_col='__order__', race_id_col='race_id')
    metrics_df = metrics_df.merge(detected.drop(columns=['row_index'], errors='ignore'), on='race_id', how='left', suffixes=('', '_detected'))
    metrics_df['regime'] = metrics_df['regime'].fillna(metrics_df['regime_detected']) if 'regime_detected' in metrics_df.columns else metrics_df['regime']
    metrics_df['regime_score'] = metrics_df['regime_score'].fillna(metrics_df['regime_score_detected']) if 'regime_score_detected' in metrics_df.columns else metrics_df.get('regime_score', 0.0)
    metrics_df['regime'] = metrics_df['regime'].fillna('stable_market')

    tracker = RegimeTransitionTracker()
    tracker.record_many(metrics_df['regime'].tolist())
    survival = RegimeSurvivalMetrics()

    analysis_frame = df.merge(
        metrics_df[['race_id', 'regime', 'regime_score']],
        on='race_id',
        how='left',
    )
    if 'pnl' not in analysis_frame.columns and 'profit' in analysis_frame.columns:
        analysis_frame['pnl'] = analysis_frame['profit']
    if 'profit' not in analysis_frame.columns and 'pnl' in analysis_frame.columns:
        analysis_frame['profit'] = analysis_frame['pnl']
    if 'stake' not in analysis_frame.columns:
        analysis_frame['stake'] = 1.0
    if 'probability' not in analysis_frame.columns:
        if prob_col in analysis_frame.columns:
            analysis_frame['probability'] = analysis_frame[prob_col]
    if 'hit' not in analysis_frame.columns and 'actual_hit' in analysis_frame.columns:
        analysis_frame['hit'] = analysis_frame['actual_hit']
    if 'uncertainty_mean' not in analysis_frame.columns:
        uncertainty_source = 'model_uncertainty' if 'model_uncertainty' in analysis_frame.columns else ('uncertainty_score' if 'uncertainty_score' in analysis_frame.columns else None)
        if uncertainty_source:
            analysis_frame['uncertainty_mean'] = analysis_frame[uncertainty_source]
        else:
            uncertainty_map = metrics_df.set_index('race_id')['uncertainty_mean'] if 'uncertainty_mean' in metrics_df.columns else pd.Series(dtype=float)
            analysis_frame['uncertainty_mean'] = analysis_frame['race_id'].map(uncertainty_map).fillna(0.0)

    # compute per-race P&L and assign regime
    # use 'pnl' as profit and assume unit stake per decision if 'stake' not present
    if 'pnl' in df.columns:
        profit_sum = df.groupby('race_id')['pnl'].sum()
    elif 'profit' in df.columns:
        profit_sum = df.groupby('race_id')['profit'].sum()
    else:
        raise RuntimeError('results CSV must contain pnl or profit column')

    if 'stake' in df.columns:
        stake_sum = df.groupby('race_id')['stake'].sum()
    else:
        stake_sum = df.groupby('race_id').size()

    agg = profit_sum.to_frame('profit_sum').join(stake_sum.to_frame('stake_sum'))
    metrics_df = metrics_df.merge(agg, how='left', left_on='race_id', right_index=True)
    metrics_df['ROI'] = metrics_df.apply(lambda r: float(r['profit_sum'] / r['stake_sum']) if (r['stake_sum'] and not np.isnan(r['stake_sum'])) else 0.0, axis=1)
    metrics_df['profit'] = metrics_df['profit_sum'].fillna(0.0)
    metrics_df['stake'] = metrics_df['stake_sum'].fillna(0.0)
    metrics_df['roi'] = metrics_df['ROI']
    metrics_df['drawdown'] = metrics_df['profit'].cumsum() - metrics_df['profit'].cumsum().cummax()

    reports = survival.summarize(
        analysis_frame,
        regime_col='regime',
        profit_col='profit',
        stake_col='stake',
        drawdown_col='drawdown',
        uncertainty_col='uncertainty_mean',
        prob_col='probability' if 'probability' in analysis_frame.columns else prob_col,
        hit_col='hit' if 'hit' in analysis_frame.columns else 'actual_hit',
        order_col='__order__',
    )

    # save requested outputs
    metrics_df.to_csv(os.path.join(out_dir, 'regime_map.csv'), index=False)
    tracker.transition_graph().to_csv(os.path.join(out_dir, 'transition_graph.csv'), index=False)
    with open(os.path.join(out_dir, 'transition_graph.dot'), 'w', encoding='utf-8') as f:
        f.write(tracker.to_dot())

    reports['roi_table'].to_csv(os.path.join(out_dir, 'regime_roi_table.csv'), index=False)
    reports['drawdown_table'].to_csv(os.path.join(out_dir, 'regime_drawdown_analysis.csv'), index=False)
    reports['calibration_table'].to_csv(os.path.join(out_dir, 'regime_calibration_analysis.csv'), index=False)
    reports['uncertainty_table'].to_csv(os.path.join(out_dir, 'regime_uncertainty_analysis.csv'), index=False)
    reports['survival_table'].to_csv(os.path.join(out_dir, 'regime_survival_analysis.csv'), index=False)

    # backward-compatible summary files
    summary = reports['survival_table'].merge(reports['roi_table'][['regime', 'roi']], on='regime', how='left') if len(reports['survival_table']) else pd.DataFrame()
    if len(summary):
        summary.to_csv(os.path.join(out_dir, 'regime_summary.csv'), index=False)
    tracker.transition_matrix().to_csv(os.path.join(out_dir, 'regime_transitions.csv'))

    print('Wrote reports to', out_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='results/backtest_full.csv')
    parser.add_argument('--out', default='reports/regimes')
    args = parser.parse_args()
    main(args.input, args.out)

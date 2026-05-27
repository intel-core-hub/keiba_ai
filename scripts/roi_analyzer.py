"""
ROIAnalyzer

Usage:
  python scripts/roi_analyzer.py --input results/backtest_full.csv --outdir results/roi_report

Purpose:
  - Provide explainable, pandas/numpy based ROI analysis for betting/prediction logs.
  - Outputs bucket tables (odds/confidence/edge/uncertainty), calibration report, ROI curves, drawdown, and basic Sharpe-like metrics.

The script is intentionally conservative about column names: it will try to auto-detect common names for
`pnl`, `stake`, `odds`, `pred_prob` (predicted probability), `expected_value` (edge), `uncertainty`, `race_datetime`, `race_class`, `market_regime`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_ODDS_BINS = [1.5, 2.5, 4, 6, 10, 999]
DEFAULT_PROB_BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def pick_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


class ROIAnalyzer:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self._normalize_columns()

    def _normalize_columns(self):
        df = self.df
        # detect common column names
        self.pnl_col = pick_column(df, ['pnl', 'profit', 'profit_loss', 'pnl_amount']) or None
        self.stake_col = pick_column(df, ['stake', 'bet', 'amount', 'wager']) or None
        self.odds_col = pick_column(df, ['odds', 'price', 'market_odds']) or None
        self.prob_col = pick_column(df, ['pred_prob', 'prob', 'model_prob', 'prediction']) or None
        self.ev_col = pick_column(df, ['expected_value', 'ev', 'edge', 'expected_return']) or None
        self.uncert_col = pick_column(df, ['uncertainty', 'uncert', 'pred_std', 'entropy']) or None
        self.datetime_col = pick_column(df, ['race_datetime', 'datetime', 'timestamp', 'date']) or None
        self.race_class_col = pick_column(df, ['race_class', 'class', 'grade', 'race_grade']) or None
        self.market_regime_col = pick_column(df, ['market_regime', 'regime']) or None

        # fallback defaults
        if self.stake_col is None:
            # assume unit stake
            df['__stake__'] = 1.0
            self.stake_col = '__stake__'
        if self.pnl_col is None:
            # try to compute pnl from finishing result and odds/hit columns if present
            # but by default leave NaN
            df['__pnl__'] = df.get('pnl', np.nan)
            self.pnl_col = '__pnl__'

        # ensure numeric
        for col in [self.stake_col, self.pnl_col, self.odds_col, self.prob_col, self.ev_col, self.uncert_col]:
            if col and col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # datetime parsing
        if self.datetime_col and self.datetime_col in df.columns:
            try:
                df[self.datetime_col] = pd.to_datetime(df[self.datetime_col], errors='coerce')
            except Exception:
                pass

        self.df = df

    def bucketize(self, col: str, bins: Optional[List[float]] = None, quantiles: Optional[int] = None, labels: Optional[List[str]] = None) -> pd.Series:
        s = self.df[col]
        if bins is not None:
            return pd.cut(s.fillna(-9999), bins=bins, labels=labels)
        if quantiles is not None:
            return pd.qcut(s.rank(method='first'), quantiles, duplicates='drop')
        raise ValueError('Either bins or quantiles required')

    def aggregate_by_bucket(self, bucket_series: pd.Series) -> pd.DataFrame:
        df = self.df.copy()
        df['_bucket'] = bucket_series
        agg = df.groupby('_bucket').agg(
            n_bets=(self.stake_col, 'count'),
            total_stake=(self.stake_col, 'sum'),
            total_pnl=(self.pnl_col, 'sum'),
            mean_ev=(self.ev_col, 'mean'),
            mean_prob=(self.prob_col, 'mean'),
        )
        agg['roi'] = agg['total_pnl'] / agg['total_stake']
        # hit rate: requires presence of pnl and stake; treat positive pnl as hit
        agg['hit_rate'] = df.groupby('_bucket').apply(lambda g: (g[self.pnl_col] > 0).sum() / max(1, len(g)))
        return agg.reset_index()

    def odds_bucket_analysis(self, bins: Optional[List[float]] = None) -> pd.DataFrame:
        if self.odds_col is None:
            raise RuntimeError('Odds column not found in data')
        bins = bins or DEFAULT_ODDS_BINS
        b = self.bucketize(self.odds_col, bins=bins)
        return self.aggregate_by_bucket(b)

    def confidence_bucket_analysis(self, bins: Optional[List[float]] = None) -> pd.DataFrame:
        if self.prob_col is None:
            raise RuntimeError('Predicted probability column not found in data')
        bins = bins or DEFAULT_PROB_BINS
        b = self.bucketize(self.prob_col, bins=bins)
        return self.aggregate_by_bucket(b)

    def edge_bucket_analysis(self, quantiles: int = 10) -> pd.DataFrame:
        if self.ev_col is None:
            raise RuntimeError('Expected value (edge) column not found')
        b = self.bucketize(self.ev_col, quantiles=quantiles)
        return self.aggregate_by_bucket(b)

    def uncertainty_bucket_analysis(self, quantiles: int = 5) -> pd.DataFrame:
        if self.uncert_col is None:
            raise RuntimeError('Uncertainty column not found')
        b = self.bucketize(self.uncert_col, quantiles=quantiles)
        return self.aggregate_by_bucket(b)

    def race_class_analysis(self) -> pd.DataFrame:
        if self.race_class_col is None:
            raise RuntimeError('race_class column not found')
        b = self.df[self.race_class_col].fillna('UNKNOWN')
        return self.aggregate_by_bucket(b)

    def market_regime_analysis(self) -> pd.DataFrame:
        if self.market_regime_col is None:
            raise RuntimeError('market_regime column not found')
        b = self.df[self.market_regime_col].fillna('UNKNOWN')
        return self.aggregate_by_bucket(b)

    def expected_vs_realized(self) -> pd.DataFrame:
        # aggregate global EV vs realized ROI per quantile of EV
        if self.ev_col is None:
            raise RuntimeError('EV column not found')
        df = self.df.copy()
        df['ev_q'] = pd.qcut(df[self.ev_col].rank(method='first'), 20, duplicates='drop')
        agg = df.groupby('ev_q').agg(
            n_bets=(self.stake_col, 'count'),
            mean_ev=(self.ev_col, 'mean'),
            total_pnl=(self.pnl_col, 'sum'),
            total_stake=(self.stake_col, 'sum')
        )
        agg['realized_roi'] = agg['total_pnl'] / agg['total_stake']
        return agg.reset_index()

    def calibration_analysis(self, prob_bins: Optional[List[float]] = None) -> pd.DataFrame:
        if self.prob_col is None:
            raise RuntimeError('pred_prob column not found')
        prob_bins = prob_bins or DEFAULT_PROB_BINS
        df = self.df.copy()
        df['prob_bin'] = pd.cut(df[self.prob_col].fillna(-1), bins=prob_bins)
        agg = df.groupby('prob_bin').agg(
            mean_pred=(self.prob_col, 'mean'),
            actual_hit_rate=(self.pnl_col, lambda s: (s > 0).sum() / max(1, len(s))),
            n=(self.prob_col, 'count')
        ).reset_index()
        # ECE simple
        total = agg['n'].sum()
        if total == 0:
            agg['abs_gap'] = np.nan
            agg['weighted_gap'] = np.nan
        else:
            agg['abs_gap'] = (agg['mean_pred'] - agg['actual_hit_rate']).abs()
            agg['weighted_gap'] = agg['abs_gap'] * (agg['n'] / total)
        return agg

    def cumulative_pnl_and_drawdown(self, time_col: Optional[str] = None) -> Dict[str, pd.Series]:
        df = self.df.copy()
        time_col = time_col or self.datetime_col
        if time_col and time_col in df.columns:
            df = df.sort_values(time_col)
        cum = df[self.pnl_col].fillna(0).cumsum()
        peak = cum.cummax()
        drawdown = cum - peak
        max_drawdown = drawdown.min()
        return {
            'cumulative': cum,
            'drawdown': drawdown,
            'max_drawdown': max_drawdown
        }

    def sharpe_like_metrics(self) -> Dict[str, float]:
        r = self.df[self.pnl_col].dropna()
        if len(r) < 2:
            return {'mean': float(r.mean()) if len(r) else 0.0, 'std': float(r.std()), 'sharpe': float('nan')}
        mean = float(r.mean())
        sd = float(r.std(ddof=1))
        sharpe = mean / sd if sd > 0 else float('nan')
        # scaled
        scaled = sharpe * math.sqrt(len(r)) if sd > 0 else float('nan')
        return {'mean': mean, 'std': sd, 'sharpe': sharpe, 'scaled_sharpe': scaled}

    def save_bucket_table(self, df: pd.DataFrame, path: str):
        df.to_csv(path, index=False)

    def plot_bar(self, df: pd.DataFrame, xcol: str, ycol: str, title: str, outpath: str):
        plt.figure(figsize=(8, 4))
        try:
            plt.bar(df[xcol].astype(str), df[ycol])
        except Exception:
            plt.bar(range(len(df)), df[ycol])
        plt.xticks(rotation=45, ha='right')
        plt.title(title)
        plt.tight_layout()
        plt.savefig(outpath)
        plt.close()


def load_csv_guess(path: str, usecols: Optional[List[str]] = None) -> pd.DataFrame:
    # be forgiving with engine and low_memory
    return pd.read_csv(path, low_memory=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', required=True, help='Input CSV (backtest/decision log)')
    p.add_argument('--outdir', '-o', default='results/roi_report', help='Output directory')
    p.add_argument('--odds-bins', nargs='+', type=float, help='Optional odds bin edges (space separated)')
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    df = load_csv_guess(args.input)
    analyzer = ROIAnalyzer(df)

    results = {}
    # odds bin
    try:
        odds_table = analyzer.odds_bucket_analysis(bins=args.odds_bins)
        out_csv = os.path.join(args.outdir, 'bucket_odds.csv')
        analyzer.save_bucket_table(odds_table, out_csv)
        analyzer.plot_bar(odds_table, '_bucket', 'roi', 'ROI by Odds Bucket', os.path.join(args.outdir, 'roi_by_odds.png'))
        results['odds_table'] = out_csv
    except Exception as e:
        results['odds_table_error'] = str(e)

    # confidence
    try:
        conf_table = analyzer.confidence_bucket_analysis()
        out_csv = os.path.join(args.outdir, 'bucket_confidence.csv')
        analyzer.save_bucket_table(conf_table, out_csv)
        analyzer.plot_bar(conf_table, '_bucket', 'roi', 'ROI by Confidence Bucket', os.path.join(args.outdir, 'roi_by_confidence.png'))
        results['confidence_table'] = out_csv
    except Exception as e:
        results['confidence_table_error'] = str(e)

    # edge
    try:
        edge_table = analyzer.edge_bucket_analysis()
        out_csv = os.path.join(args.outdir, 'bucket_edge.csv')
        analyzer.save_bucket_table(edge_table, out_csv)
        analyzer.plot_bar(edge_table, '_bucket', 'roi', 'ROI by Edge Bucket', os.path.join(args.outdir, 'roi_by_edge.png'))
        results['edge_table'] = out_csv
    except Exception as e:
        results['edge_table_error'] = str(e)

    # uncertainty
    try:
        uncert_table = analyzer.uncertainty_bucket_analysis()
        out_csv = os.path.join(args.outdir, 'bucket_uncertainty.csv')
        analyzer.save_bucket_table(uncert_table, out_csv)
        analyzer.plot_bar(uncert_table, '_bucket', 'roi', 'ROI by Uncertainty Bucket', os.path.join(args.outdir, 'roi_by_uncertainty.png'))
        results['uncertainty_table'] = out_csv
    except Exception as e:
        results['uncertainty_table_error'] = str(e)

    # expected vs realized
    try:
        ev_table = analyzer.expected_vs_realized()
        out_csv = os.path.join(args.outdir, 'ev_vs_realized.csv')
        ev_table.to_csv(out_csv, index=False)
        analyzer.plot_bar(ev_table, 'ev_q', 'realized_roi', 'Realized ROI by EV Quantile', os.path.join(args.outdir, 'realized_by_ev.png'))
        results['ev_table'] = out_csv
    except Exception as e:
        results['ev_table_error'] = str(e)

    # calibration
    try:
        calib = analyzer.calibration_analysis()
        out_csv = os.path.join(args.outdir, 'calibration.csv')
        calib.to_csv(out_csv, index=False)
        # plot predicted vs actual
        plt.figure(figsize=(6, 4))
        plt.plot(calib['mean_pred'], calib['actual_hit_rate'], marker='o')
        plt.plot([0, 1], [0, 1], '--', color='gray')
        plt.xlabel('Mean Predicted')
        plt.ylabel('Actual Hit Rate')
        plt.title('Calibration: predicted vs actual')
        plt.tight_layout()
        plt.savefig(os.path.join(args.outdir, 'calibration.png'))
        plt.close()
        results['calibration'] = out_csv
    except Exception as e:
        results['calibration_error'] = str(e)

    # cumulative / drawdown
    try:
        cd = analyzer.cumulative_pnl_and_drawdown()
        cum = cd['cumulative']
        drawdown = cd['drawdown']
        plt.figure(figsize=(8, 4))
        plt.plot(cum)
        plt.title('Cumulative PnL')
        plt.tight_layout()
        plt.savefig(os.path.join(args.outdir, 'cumulative_pnl.png'))
        plt.close()
        plt.figure(figsize=(8, 4))
        plt.plot(drawdown)
        plt.title('Drawdown')
        plt.tight_layout()
        plt.savefig(os.path.join(args.outdir, 'drawdown.png'))
        plt.close()
        results['cumulative_plot'] = 'cumulative_pnl.png'
    except Exception as e:
        results['cumulative_error'] = str(e)

    # sharpe-like
    try:
        metrics = analyzer.sharpe_like_metrics()
        results['metrics'] = metrics
    except Exception as e:
        results['metrics_error'] = str(e)

    # save summary
    with open(os.path.join(args.outdir, 'summary.json'), 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print('ROI analysis completed. Outputs in', args.outdir)


if __name__ == '__main__':
    main()

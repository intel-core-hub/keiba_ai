"""Simulate backtest applying RegimeAwareRiskManager + BetSizer.

Usage:
    python tools/simulate_regime_backtest.py --input results/backtest_recalc.csv --out reports/regimes_simulation --top-n 1 --ev-threshold 1.0
"""
import os
import sys
import argparse
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.market.regime_metrics import batch_compute_metrics
from core.market.regime_classifier import RegimeClassifier
from core.betting.regime_risk_manager import RegimeAwareRiskManager
from core.betting.bet_sizer import BetConfig, BetSizer


def simulate(input_csv: str, out_dir: str, top_n: int = 1, ev_threshold: float = 1.0, initial_bankroll: float = 20000.0):
    os.makedirs(out_dir, exist_ok=True)
    df = pd.read_csv(input_csv)

    # compute per-race metrics and regimes
    metrics_df = batch_compute_metrics(df, race_id_col='race_id', odds_col='odds', prob_col='pred_prob', uncertainty_col='model_uncertainty')
    clf = RegimeClassifier(mode='rules')
    metrics_df['regime'] = metrics_df.apply(lambda r: clf.predict(r.to_dict()), axis=1)

    # prepare bet sizing
    bet_cfg = BetConfig()
    sizer = BetSizer(bet_cfg)
    regime_mgr = RegimeAwareRiskManager(base_min_edge=bet_cfg.min_edge)

    bankroll = float(initial_bankroll)
    results = []

    # iterate races in chronological order if available
    race_order = df['race_id'].unique().tolist()
    for race_id in race_order:
        grp = df[df['race_id'] == race_id].copy()
        if grp.empty:
            continue

        # reset per-race exposure
        sizer.reset_race()

        # regime for this race
        if race_id in metrics_df.index:
            regime = metrics_df.loc[race_id, 'regime']
        else:
            regime = 'stable_market'

        # select candidates (EV strategy)
        grp = grp.sort_values('expected_value', ascending=False)
        candidates = grp[grp['expected_value'] >= ev_threshold].head(top_n)

        for _, row in candidates.iterrows():
            odds = float(row['odds'])
            prob = float(row['pred_prob']) if 'pred_prob' in row and not np.isnan(row['pred_prob']) else (1.0 / odds if odds > 0 else 0.0)
            market_prob = 1.0 / odds if odds > 0 else 0.0
            edge = prob - market_prob

            # check regime gating
            uncertainty = float(row['model_uncertainty']) if 'model_uncertainty' in row and not np.isnan(row['model_uncertainty']) else 0.0
            if not regime_mgr.should_bet(regime, edge, uncertainty):
                results.append({
                    'race_id': race_id,
                    'horse_name': row.get('horse_name', ''),
                    'regime': regime,
                    'odds': odds,
                    'prob': prob,
                    'edge': edge,
                    'bet_size': 0.0,
                    'profit': 0.0,
                    'skipped': True,
                })
                continue

            mult = regime_mgr.get_exposure_multiplier(regime)
            risk_multiplier = float(mult)

            bet = sizer.calculate_bet(bankroll=bankroll, prob=prob, odds=odds, risk_multiplier=risk_multiplier)
            if bet <= 0:
                results.append({
                    'race_id': race_id,
                    'horse_name': row.get('horse_name',''),
                    'regime': regime,
                    'odds': odds,
                    'prob': prob,
                    'edge': edge,
                    'bet_size': 0.0,
                    'profit': 0.0,
                    'skipped': True,
                })
                continue

            hit = False
            if 'actual_pos' in row:
                try:
                    hit = int(row['actual_pos']) == 1
                except Exception:
                    hit = False

            profit = bet * (odds - 1) if hit else -bet
            bankroll += profit

            results.append({
                'race_id': race_id,
                'horse_name': row.get('horse_name',''),
                'regime': regime,
                'odds': odds,
                'prob': prob,
                'edge': edge,
                'bet_size': bet,
                'profit': profit,
                'skipped': False,
            })

    res_df = pd.DataFrame.from_records(results)
    # per-regime aggregation
    agg = res_df.groupby('regime').agg(
        n_bets=('bet_size', lambda x: (x>0).sum()),
        total_profit=('profit', 'sum'),
        total_stake=('bet_size', 'sum'),
    ).reset_index()
    agg['ROI'] = agg.apply(lambda r: (r['total_profit'] / r['total_stake']) if r['total_stake']>0 else float('nan'), axis=1)

    res_df.to_csv(os.path.join(out_dir, 'simulated_trades.csv'), index=False)
    agg.to_csv(os.path.join(out_dir, 'regime_agg.csv'), index=False)
    # also write bankroll time series
    res_df['bankroll'] = initial_bankroll + res_df['profit'].cumsum().fillna(0)
    res_df[['race_id','horse_name','regime','bet_size','profit','bankroll','skipped']].to_csv(os.path.join(out_dir,'bankroll_ts.csv'), index=False)

    print('Wrote simulation reports to', out_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', '-i', default='results/backtest_recalc.csv')
    parser.add_argument('--out', '-o', default='reports/regimes_simulation')
    parser.add_argument('--top-n', type=int, default=1)
    parser.add_argument('--ev-threshold', type=float, default=1.0)
    parser.add_argument('--bankroll', type=float, default=20000.0)
    args = parser.parse_args()
    simulate(args.input, args.out, top_n=args.top_n, ev_threshold=args.ev_threshold, initial_bankroll=args.bankroll)

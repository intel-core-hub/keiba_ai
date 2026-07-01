"""Replay engine: read decision log, reconstruct state, validate, and emit report."""
import os
import json
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.audit.historical_snapshot_loader import HistoricalSnapshotLoader
from core.audit.decision_reconstruction import DecisionReconstruction
from core.audit.replay_validator import ReplayValidator


def load_decisions(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    recs = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except Exception:
                continue
    return recs


def run_replay(decision_log_path='logs/decisions.jsonl', outdir='reports/replay'):
    os.makedirs(outdir, exist_ok=True)

    decisions = load_decisions(decision_log_path)

    loader = HistoricalSnapshotLoader()
    recon = DecisionReconstruction(loader)
    validator = ReplayValidator()

    summary = {
        'total': len(decisions),
        'anomalies': [],
    }

    out_rows = []

    for d in decisions:
        r = recon.reconstruct(d)
        r['decision'] = d.get('decision')
        # run validators
        ts_anom, ts_reason = validator.timestamp_anomaly(r)
        fm_anom, fm_reason = validator.feature_mismatch(r)
        imp_anom, imp_reason = validator.impossible_decision(r)

        anomaly_reasons = [x for x in [ts_reason, fm_reason, imp_reason] if x]
        if anomaly_reasons:
            summary['anomalies'].append({'decision_id': r.get('decision_id'), 'reasons': anomaly_reasons})

        out_rows.append({
            'decision_id': r.get('decision_id'),
            'race_id': r.get('race_id'),
            'selection': r.get('selection'),
            'timestamp': r.get('timestamp'),
            'snapshot_available': r.get('snapshot_available'),
            'mismatch_count': len(r.get('mismatches', [])),
            'anomaly_reasons': anomaly_reasons,
        })

    # write CSV
    import csv
    csv_path = os.path.join(outdir, 'replay_report.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
        fieldnames = ['decision_id','race_id','selection','timestamp','snapshot_available','mismatch_count','anomaly_reasons']
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        for r in out_rows:
            writer.writerow(r)

    # write anomalies JSON
    with open(os.path.join(outdir, 'anomalies.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print('Replay completed. Reports in', outdir)


if __name__ == '__main__':
    run_replay()

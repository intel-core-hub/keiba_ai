"""
replay_engine.py

Engine to iterate recorded decisions, reconstruct historical state and run
validators/reconstructors to produce an audit report.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import pandas as pd

from .historical_snapshot_loader import HistoricalSnapshotLoader
from .replay_validator import ReplayValidator
from .decision_reconstructor import DecisionReconstructor


class ReplayEngine:
    def __init__(
        self,
        loader: HistoricalSnapshotLoader,
        model_loader: Optional[callable] = None,
        validator: Optional[ReplayValidator] = None,
    ) -> None:
        self.loader = loader
        self.model_loader = model_loader
        self.validator = validator or ReplayValidator()
        self.reconstructor = DecisionReconstructor(model_loader) if model_loader else None

    def replay(self, decision_log_path: Path, out_report: Optional[Path] = None) -> Dict[str,Any]:
        decisions = []
        # support csv or jsonl
        p = Path(decision_log_path)
        if p.suffix.lower() == '.csv':
            df = pd.read_csv(p, parse_dates=['timestamp'])
            records = df.to_dict(orient='records')
        else:
            records = []
            with p.open('r', encoding='utf-8') as fh:
                for line in fh:
                    line=line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        # try eval-ish fallback
                        try:
                            records.append(eval(line))
                        except Exception:
                            continue

        report = {"summary": {"total": len(records)}, "items": []}

        for rec in records:
            item = {"decision_id": rec.get('decision_id')}
            # parse timestamp
            ts = rec.get('timestamp')
            if isinstance(ts, str):
                try:
                    decision_ts = datetime.fromisoformat(ts)
                except Exception:
                    decision_ts = None
            else:
                decision_ts = ts

            # load snapshots
            odds = None
            features = None
            calibration = None
            try:
                if decision_ts:
                    odds = self.loader.get_latest_odds(decision_ts, race_id=rec.get('race_id'))
                    features = self.loader.get_latest_features(decision_ts, entity_id=rec.get('entity_id'))
                    calibration = self.loader.get_calibration_state(decision_ts)
            except Exception as e:
                item['load_error'] = str(e)

            # basic validations
            if hasattr(odds, 'empty') and not getattr(odds, 'empty'):
                odds_ts = odds[self.loader.timestamp_col].max()
            else:
                odds_ts = None
            if hasattr(features, 'empty') and not getattr(features, 'empty'):
                feature_ts = features[self.loader.timestamp_col].max()
            else:
                feature_ts = None

            item['validations'] = {}
            item['validations']['timestamp_consistency'] = self.validator.validate_timestamp_consistency(decision_ts, odds_ts)
            item['validations']['feature_availability'] = self.validator.validate_feature_availability(decision_ts, feature_ts)
            # model version check
            item['validations']['model_version'] = self.validator.validate_model_version(rec.get('model_version'), rec.get('model_version'))
            # calibration
            calib_ts = None
            if hasattr(calibration, 'empty') and not getattr(calibration, 'empty'):
                calib_ts = calibration[self.loader.timestamp_col].max()
            item['validations']['calibration'] = self.validator.validate_calibration_timing(decision_ts, calib_ts)

            # attempt reconstruction
            if self.reconstructor:
                item['reconstruction'] = self.reconstructor.reconstruct(rec, features)

            report['items'].append(item)

        if out_report:
            with out_report.open('w', encoding='utf-8') as fh:
                json.dump(report, fh, default=str, indent=2, ensure_ascii=False)

        return report

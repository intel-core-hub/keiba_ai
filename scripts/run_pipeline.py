import argparse
import os
import sys
import traceback
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.collect_data import collect
from data.historical_dataset import HistoricalDatasetBuilder
from learning.trainer import SurvivalModelTrainer
from validation.walk_forward_validation import WalkForwardValidator
from simulation.live_simulation import LiveSimulation


def run_pipeline(date: str, collect_limit: int = 10, model_out: str = "models/prediction_model.pkl"):
    try:
        print("[pipeline] collect data")
        collected = collect(date, limit=collect_limit)

        print("[pipeline] build processed dataset")
        builder = HistoricalDatasetBuilder()
        df = builder.build()

        if df is None or df.empty:
            raise RuntimeError("processed dataset empty — aborting pipeline")

        print("[pipeline] train model")
        trainer = SurvivalModelTrainer(model_path=model_out)
        dataset_path = os.path.join(builder.processed_dir, "historical_dataset.csv")
        trainer.train(dataset_path)

        print("[pipeline] validate (walk-forward)")
        try:
            validator = WalkForwardValidator(train_window=max(10, len(df) // 2), test_window=max(5, len(df) // 4), step_size=max(5, len(df) // 4))
            if hasattr(validator, "validate"):
                validator.validate(df)
        except Exception as e:
            print(f"validator error: {e}")

        print("[pipeline] run live simulation")
        sim = LiveSimulation()
        if hasattr(sim, "run"):
            sim.run(df)
        else:
            print("LiveSimulation has no run(df) — skipping")

        print("[pipeline] done")
    except Exception:
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Run end-to-end pipeline: collect -> build -> train -> validate -> simulate")
    parser.add_argument("date", help="Date to collect (e.g. 20240106)")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    run_pipeline(args.date, collect_limit=args.limit)


if __name__ == "__main__":
    main()

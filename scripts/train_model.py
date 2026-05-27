import os
import sys
import argparse
import traceback
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.historical_dataset import HistoricalDatasetBuilder
from learning.trainer import SurvivalModelTrainer


def train(out_model_path: str = "models/prediction_model.pkl"):
    os.makedirs(os.path.dirname(out_model_path), exist_ok=True)

    builder = HistoricalDatasetBuilder()
    print("Building historical dataset...")
    df = builder.build()
    if df is None or df.empty:
        raise RuntimeError("processed dataset is empty (check data/raw/) ")

    trainer = SurvivalModelTrainer(model_path=out_model_path)
    print("Training model...")
    dataset_path = os.path.join(builder.processed_dir, "historical_dataset.csv")
    metrics = trainer.train(dataset_path)

    print("Metrics:", metrics)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Train survival prediction model from processed data")
    parser.add_argument("--out", default="models/prediction_model.pkl")
    args = parser.parse_args()
    try:
        train(args.out)
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()

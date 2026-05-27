import time
import argparse
import traceback

from simulation.live_simulation import LiveSimulation
from data.historical_dataset import HistoricalDatasetBuilder


def schedule_once(interval_sec: int = 3600):
    builder = HistoricalDatasetBuilder()
    sim = LiveSimulation()
    while True:
        try:
            print("[scheduler] building dataset and running simulation")
            df = builder.build()
            if df is None:
                print("no data — sleeping")
            else:
                sim.run(df)
        except Exception:
            traceback.print_exc()
        print(f"[scheduler] sleeping {interval_sec}s")
        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="Simple scheduler to run live_simulation periodically")
    parser.add_argument("--interval", type=int, default=3600, help="seconds between runs")
    args = parser.parse_args()
    schedule_once(args.interval)


if __name__ == "__main__":
    main()

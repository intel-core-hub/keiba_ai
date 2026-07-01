import asyncio
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
from core.predictor import Predictor
import numpy as np
import time

class SlowMockModel:
    def predict_proba(self, X):
        # simulate slow model
        time.sleep(0.05)
        return np.array([[0.3, 0.7]])

async def main():
    p = Predictor()
    p.trained = True
    p.model = SlowMockModel()
    p.feature_names = ['f1','f2','f3']
    p._feature_idx = {f:i for i,f in enumerate(p.feature_names)}
    p._n_features = len(p.feature_names)
    p.enable_predict_raw_profiling(True)

    loop = asyncio.get_running_loop()
    tasks = []
    n_tasks = 20
    start = time.perf_counter()
    for i in range(n_tasks):
        submitted = time.perf_counter()
        # schedule many concurrent predict calls
        t = loop.run_in_executor(p.predict_executor, p.predict_raw, {'f1':1,'f2':2,'f3':3}, None, submitted)
        tasks.append(t)
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    print('results sample:', results[:3])
    print('elapsed', elapsed)
    print('stats', p.get_predict_raw_stats())

if __name__ == '__main__':
    asyncio.run(main())

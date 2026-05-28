import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
from core.predictor import Predictor
import numpy as np
class MockModel:
    def predict_proba(self, X):
        return np.array([[0.3, 0.7]])

p = Predictor()
# inject mock trained model
p.trained = True
p.model = MockModel()
p.feature_names = ['f1','f2','f3']
p._feature_idx = {f:i for i,f in enumerate(p.feature_names)}
p._n_features = len(p.feature_names)
# enable profiling
p.enable_predict_raw_profiling(True)
for i in range(3):
    prob = p.predict_raw({'f1':1.0,'f2':2.0,'f3':3.0})
    print('prob', prob)
print('stats', p.get_predict_raw_stats())

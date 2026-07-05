import importlib
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mods = [
    'core.low_latency_execution',
    'core.predictor',
]

for m in mods:
    try:
        importlib.import_module(m)
        print(m + ' OK')
    except Exception as e:
        print(m + ' ERROR', e)

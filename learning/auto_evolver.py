import yaml

from learning.performance_analyzer import PerformanceAnalyzer
from learning.strategy_updater import StrategyUpdater


def evolve():

    analyzer = PerformanceAnalyzer()
    updater = StrategyUpdater()

    metrics = analyzer.analyze()

    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)

    new_settings = updater.update(metrics, settings)

    with open("config/settings.yaml", "w") as f:
        yaml.dump(new_settings, f)


class AutoEvolver:

    def run(self):
        evolve()
from learning.strategy_updater import StrategyUpdater


class Updater:

	def update(self, metrics, settings):
		return StrategyUpdater().update(metrics, settings)

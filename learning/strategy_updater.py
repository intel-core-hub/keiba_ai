class StrategyUpdater:

    def update(self, metrics, settings):

        # Brier悪化 → 保守化
        if metrics["brier"] > 0.18:
            settings["kelly_mult"] *= 0.9
            settings["min_edge"] += 0.005

        # ROI良好 → 徐々に拡張
        if metrics["roi"] > 0:
            settings["kelly_mult"] *= 1.02

        settings["kelly_mult"] = min(
            max(settings["kelly_mult"], 0.3), 1.0
        )

        return settings
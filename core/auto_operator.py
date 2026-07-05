from core.regime_detector import RegimeDetector


class AutoOperator:
    def __init__(self, risk_manager, stop_drawdown: float = 0.35):
        self.risk_manager = risk_manager
        self.stop_drawdown = stop_drawdown
        self.regime_detector = RegimeDetector()
        self.running = True

    def emergency_stop(self) -> bool:
        drawdown = 0.0
        if hasattr(self.risk_manager, "drawdown"):
            drawdown = float(self.risk_manager.drawdown())
        return drawdown >= self.stop_drawdown

    def update_mode(self) -> str:
        drawdown = 0.0
        if hasattr(self.risk_manager, "drawdown"):
            drawdown = float(self.risk_manager.drawdown())

        if drawdown >= self.stop_drawdown:
            return "HALT"
        if drawdown >= self.stop_drawdown * 0.7:
            return "DEFENSIVE"
        return "NORMAL"

    def status(self):
        return {
            "running": self.running,
            "drawdown": float(self.risk_manager.drawdown()) if hasattr(self.risk_manager, "drawdown") else 0.0,
            "bankroll": getattr(self.risk_manager, "bankroll", None),
        }

    def assess(self, stats):
        return {
            "mode": self.update_mode(),
            "emergency_stop": self.emergency_stop(),
            "stats": stats,
        }

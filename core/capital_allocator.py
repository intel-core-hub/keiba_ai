from core.portfolio_allocator import PortfolioAllocator


class CapitalAllocator:
    def __init__(self, max_fraction: float = 0.15):
        self.max_fraction = max_fraction
        self.portfolio_allocator = PortfolioAllocator()

    def allocate(self, bankroll: float, edge: float, probability: float, odds: float) -> float:
        if bankroll <= 0 or edge <= 0 or probability <= 0 or odds <= 1:
            return 0.0

        raw_fraction = min(self.max_fraction, max(0.0, edge * probability * 0.5))
        return bankroll * raw_fraction

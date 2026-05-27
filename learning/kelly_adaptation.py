class KellyAdapter:

    def __init__(self):
        self.mult = 1.0

    def update(self, brier):

        if brier > 0.18:
            self.mult *= 0.9

        elif brier < 0.13:
            self.mult *= 1.05

        self.mult = min(max(self.mult, 0.3), 1.2)

    def get_multiplier(self):
        return self.mult


KellyAdaptation = KellyAdapter

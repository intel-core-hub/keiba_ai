class ModelHealth:

    def __init__(self):
        self.health = 1.0

    def update(
        self,
        recent_roi,
        brier,
        ece=None,
        reliability=None,
        uncertainty=None,
    ):

        if recent_roi < -0.1:
            self.health *= 0.95

        if brier > 0.2:
            self.health *= 0.9

        if ece is not None:
            if ece > 0.06:
                self.health *= 0.88
            elif ece > 0.04:
                self.health *= 0.94

        if reliability is not None:
            if reliability < 0.90:
                self.health *= 0.85
            elif reliability < 0.94:
                self.health *= 0.93

        if uncertainty is not None and uncertainty > 0.65:
            self.health *= 0.92

        if recent_roi > 0:
            self.health *= 1.02

        self.health = min(max(self.health, 0.5), 1.1)

    def factor(self):
        return self.health
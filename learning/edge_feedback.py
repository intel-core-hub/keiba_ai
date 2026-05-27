class EdgeFeedback:

    def __init__(self):
        self.penalty = 1.0

    def update(self, hit, edge):

        # 外れた大Edgeは危険
        if not hit and edge > 0.1:
            self.penalty *= 0.97

        # 的中は少し回復
        if hit:
            self.penalty *= 1.01

        self.penalty = min(max(self.penalty, 0.6), 1.2)

    def adjust_edge(self, edge):
        return edge * self.penalty
# schemas/race_schema.py

import numpy as np

from dataclasses import (
    dataclass,
    asdict,
)

from typing import Optional
from datetime import datetime


# =====================================================
# Horse Feature Schema
# =====================================================

@dataclass
class HorseFeatures:
    """
    Horse Feature Schema

    目的:
    - feature固定化
    - leakage防止
    - pipeline統一
    - training consistency

    最重要:
    「特徴量定義を固定する」
    """

    # =================================================
    # Identity
    # =================================================

    race_id: str

    horse_id: str

    horse_name: str

    # =================================================
    # Race Context
    # =================================================

    race_date: str

    track: str

    distance: int

    surface: str

    weather: str

    gate: int

    field_size: int

    # =================================================
    # Odds
    # =================================================

    odds: float

    favorite_rank: int

    # =================================================
    # Horse Ability
    # =================================================

    speed_index: float

    stamina_index: float

    acceleration_index: float

    consistency_index: float

    closing_speed: float

    # =================================================
    # Form
    # =================================================

    last_finish: int

    avg_finish_last5: float

    recent_form_score: float

    rest_days: int

    weight_change: float

    # =================================================
    # Human Factors
    # =================================================

    jockey_score: float

    trainer_score: float

    stable_score: float

    # =================================================
    # Market / Value
    # =================================================

    market_support: float

    odds_value: float

    public_confidence: float

    # =================================================
    # Environmental Match
    # =================================================

    track_affinity: float

    distance_affinity: float

    weather_affinity: float

    pace_affinity: float

    # =================================================
    # Engineered Features
    # =================================================

    rank_score: float

    composite_score: float

    volatility_score: float

    uncertainty_score: float

    # =================================================
    # Optional Labels
    # =================================================

    target_win: Optional[int] = None

    target_place: Optional[int] = None

    finishing_position: Optional[int] = None

    # =================================================
    # Metadata
    # =================================================

    created_at: str = (
        datetime.utcnow().isoformat()
    )

    # =================================================
    # Validation
    # =================================================

    def validate(self):

        # -----------------------------------------
        # odds
        # -----------------------------------------

        if self.odds <= 0:

            raise ValueError(
                "odds must be positive"
            )

        # -----------------------------------------
        # probabilities
        # -----------------------------------------

        probability_fields = [

            "market_support",

            "public_confidence",

            "track_affinity",

            "distance_affinity",

            "weather_affinity",

            "pace_affinity",

            "consistency_index",
        ]

        for field in probability_fields:

            value = getattr(
                self,
                field,
            )

            if not (
                0 <= value <= 1
            ):

                raise ValueError(
                    f"{field} must be between 0 and 1"
                )

        # -----------------------------------------
        # positions
        # -----------------------------------------

        if self.last_finish < 1:

            raise ValueError(
                "last_finish invalid"
            )

        if self.favorite_rank < 1:

            raise ValueError(
                "favorite_rank invalid"
            )

        # -----------------------------------------
        # field size
        # -----------------------------------------

        if self.field_size < 2:

            raise ValueError(
                "field_size invalid"
            )

        return True

    # =================================================
    # To Dict
    # =================================================

    def to_dict(self):

        return asdict(self)

    # =================================================
    # Feature Vector
    # =================================================

    def feature_vector(self):

        """
        ML入力用

        NOTE:
        leakage防止のため
        target系は除外
        """

        excluded = {

            "race_id",

            "horse_id",

            "horse_name",

            "race_date",

            "created_at",

            "target_win",

            "target_place",

            "finishing_position",
        }

        data = self.to_dict()

        return {

            k: v

            for k, v in data.items()

            if k not in excluded
        }

    # =================================================
    # Survival Risk
    # =================================================

    def survival_risk(self):

        """
        不安定馬検知
        """

        risk = 0.0

        # -----------------------------------------
        # high odds risk
        # -----------------------------------------

        if self.odds > 20:
            risk += 0.25

        elif self.odds > 10:
            risk += 0.15

        # -----------------------------------------
        # uncertainty
        # -----------------------------------------

        risk += (
            self.uncertainty_score
            * 0.4
        )

        # -----------------------------------------
        # volatility
        # -----------------------------------------

        risk += (
            self.volatility_score
            * 0.3
        )

        # -----------------------------------------
        # poor consistency
        # -----------------------------------------

        risk += (
            (1 - self.consistency_index)
            * 0.2
        )

        return round(
            min(risk, 1.0),
            4,
        )

    # =================================================
    # Confidence Score
    # =================================================

    def confidence_score(self):

        """
        総合信頼度
        """

        confidence = np.mean([

            self.consistency_index,

            self.track_affinity,

            self.distance_affinity,

            self.recent_form_score,

            self.market_support,
        ])

        confidence -= (
            self.uncertainty_score
            * 0.3
        )

        return round(
            max(
                min(confidence, 1.0),
                0.0,
            ),
            4,
        )


# =====================================================
# Schema Utilities
# =====================================================

class RaceSchemaUtils:

    @staticmethod
    def validate_batch(
        records,
    ):

        valid = []

        errors = []

        for i, r in enumerate(records):

            try:

                r.validate()

                valid.append(r)

            except Exception as e:

                errors.append({

                    "index": i,

                    "horse_id":
                        getattr(
                            r,
                            "horse_id",
                            None,
                        ),

                    "error":
                        str(e),
                })

        return {

            "valid_count":
                len(valid),

            "error_count":
                len(errors),

            "errors":
                errors,
        }

    # =================================================
    # Leakage Detection
    # =================================================

    @staticmethod
    def detect_leakage(
        feature_names,
    ):

        """
        危険特徴量検知
        """

        suspicious_keywords = [

            "result",

            "finish",

            "target",

            "payout",

            "win",

            "place",

            "after",

            "final_odds",

            "closing_odds",
        ]

        detected = []

        for f in feature_names:

            lower = f.lower()

            for keyword in (
                suspicious_keywords
            ):

                if keyword in lower:

                    detected.append(f)

        return detected

    # =================================================
    # Required Fields
    # =================================================

    @staticmethod
    def required_fields():

        return [

            "race_id",

            "horse_id",

            "horse_name",

            "odds",

            "speed_index",

            "recent_form_score",

            "rank_score",

            "uncertainty_score",
        ]


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    horse = HorseFeatures(

        # identity
        race_id="2026_05_10_TOKYO_11R",

        horse_id="H001",

        horse_name="DeepImpactX",

        # race context
        race_date="2026-05-10",

        track="TOKYO",

        distance=2400,

        surface="TURF",

        weather="SUNNY",

        gate=5,

        field_size=18,

        # odds
        odds=4.5,

        favorite_rank=2,

        # ability
        speed_index=91.2,

        stamina_index=88.4,

        acceleration_index=90.1,

        consistency_index=0.82,

        closing_speed=89.3,

        # form
        last_finish=2,

        avg_finish_last5=2.4,

        recent_form_score=0.78,

        rest_days=21,

        weight_change=-2,

        # human
        jockey_score=0.84,

        trainer_score=0.80,

        stable_score=0.77,

        # market
        market_support=0.72,

        odds_value=0.68,

        public_confidence=0.69,

        # environment
        track_affinity=0.81,

        distance_affinity=0.86,

        weather_affinity=0.75,

        pace_affinity=0.73,

        # engineered
        rank_score=0.83,

        composite_score=0.81,

        volatility_score=0.24,

        uncertainty_score=0.18,

        # target
        target_win=1,
    )

    horse.validate()

    print(
        horse.feature_vector()
    )

    print(
        "\nRisk:",
        horse.survival_risk()
    )

    print(
        "\nConfidence:",
        horse.confidence_score()
    )
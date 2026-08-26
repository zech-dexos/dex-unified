import random
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ForecastResult:
    confidence: float
    time_to_action: int
    risk_penalty: float

class PredictiveValenceScorer:
    def __init__(self):
        self.baseline_valence = 0.85

    def score(self, timestamp: datetime) -> ForecastResult:
        # Calculate a stable predictive valence score
        confidence = round(random.uniform(0.75, 0.99), 2)
        time_to_action = random.randint(180, 600)
        risk_penalty = round(random.uniform(0.01, 0.15), 2)
        return ForecastResult(
            confidence=confidence,
            time_to_action=time_to_action,
            risk_penalty=risk_penalty
        )

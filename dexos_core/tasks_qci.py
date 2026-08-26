from dataclasses import dataclass
from datetime import datetime
from dexos_core.forecasting.pvs import ForecastResult

@dataclass
class QCI_Task:
    id: str
    forecast: ForecastResult
    script: str
    scheduled_at: datetime

    @property
    def dict(self):
        return {
            "id": self.id,
            "confidence": self.forecast.confidence,
            "time_to_action": self.forecast.time_to_action,
            "risk_penalty": self.forecast.risk_penalty,
            "script": self.script,
            "scheduled_at": self.scheduled_at.isoformat()
        }

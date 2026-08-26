from datetime import datetime

class QCI_Task:
    def __init__(self, id: str, forecast: object, script: str, scheduled_at: datetime):
        self.id = id
        self.forecast = forecast
        self.script = script
        self.scheduled_at = scheduled_at

    @property
    def dict(self) -> dict:
        return {
            "id": self.id,
            "forecast": getattr(self.forecast, "dict", {}),
            "script": self.script,
            "scheduled_at": self.scheduled_at.isoformat(),
        }

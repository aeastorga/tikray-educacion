"""Los instantes se guardan en UTC; las fechas de calendario se deciden en hora de Lima."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

LIMA = ZoneInfo("America/Lima")


def hoy_lima() -> date:
    return datetime.now(UTC).astimezone(LIMA).date()

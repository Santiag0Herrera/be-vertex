import datetime
import logging
import os

import httpx


logger = logging.getLogger(__name__)


class BusinessCalendarService:
    """Resolves Argentine banking settlement dates with a cached holiday calendar."""

    DEFAULT_API_URL = "https://api.argentinadatos.com/v1/feriados/{year}"
    _holiday_cache: dict[int, set[datetime.date]] = {}

    def __init__(self):
        self.api_url = os.getenv(
            "ARGENTINA_HOLIDAYS_API_URL",
            self.DEFAULT_API_URL,
        )
        self.timeout_seconds = float(
            os.getenv("ARGENTINA_HOLIDAYS_API_TIMEOUT_SECONDS", "5")
        )
        self.extra_bank_holidays = self._parse_extra_bank_holidays(
            os.getenv("ARGENTINA_BANK_HOLIDAYS", "")
        )

    @staticmethod
    def _parse_extra_bank_holidays(value: str) -> set[datetime.date]:
        holidays = set()
        for raw_date in value.split(","):
            raw_date = raw_date.strip()
            if not raw_date:
                continue
            try:
                holidays.add(datetime.date.fromisoformat(raw_date))
            except ValueError:
                logger.warning(
                    "Ignoring invalid ARGENTINA_BANK_HOLIDAYS date value=%s",
                    raw_date,
                )
        return holidays

    async def get_holidays(self, year: int) -> set[datetime.date]:
        cached = self._holiday_cache.get(year)
        if cached is not None:
            return cached | self.extra_bank_holidays

        holidays: set[datetime.date] = set()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.api_url.format(year=year))
                response.raise_for_status()
                payload = response.json()

            if not isinstance(payload, list):
                raise ValueError("Holiday API response must be a list")

            for item in payload:
                if not isinstance(item, dict):
                    continue
                date_value = item.get("fecha") or item.get("date")
                if date_value:
                    holidays.add(datetime.date.fromisoformat(str(date_value)[:10]))

            self._holiday_cache[year] = holidays
            logger.info(
                "Argentine holiday calendar loaded year=%s holidays=%s",
                year,
                len(holidays),
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            # Cache the degraded result to avoid one external request per transaction.
            self._holiday_cache[year] = set()
            logger.warning(
                "Holiday API unavailable; using weekends and configured bank holidays "
                "year=%s error=%s",
                year,
                exc,
            )

        return self._holiday_cache[year] | self.extra_bank_holidays

    async def get_settlement_date(self, transaction_date: datetime.date) -> datetime.date:
        """Return the same date when enabled, otherwise the next business date."""
        candidate = transaction_date

        # The limit protects the job from bad calendar data without hiding the failure.
        for _ in range(15):
            holidays = await self.get_holidays(candidate.year)
            if candidate.weekday() < 5 and candidate not in holidays:
                return candidate
            candidate += datetime.timedelta(days=1)

        raise RuntimeError(
            f"Could not resolve a business date after {transaction_date.isoformat()}"
        )

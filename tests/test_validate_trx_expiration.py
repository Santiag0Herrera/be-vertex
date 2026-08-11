import datetime
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://vertex_test:vertex_test@localhost/vertex_test",
)

from app.jobs.validate_trx import get_expiration_cutoff


def test_calendar_month_cutoff_handles_end_of_month():
    reference_time = datetime.datetime(2026, 2, 28, 12, 0)

    cutoff = get_expiration_cutoff(reference_time)

    assert cutoff == datetime.datetime(2026, 1, 28, 12, 0)

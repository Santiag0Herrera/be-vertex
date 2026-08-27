from datetime import datetime

import pytest

from app.services.extractor.extractors import extract_fields_from_wallet_lines
from app.services.extractor.parsers import parse_date


@pytest.mark.parametrize(
    ("line", "expected_value", "expected_date"),
    [
        (
            "21/08/2026 17:24:29",
            "21/08/2026 17:24:29",
            datetime(2026, 8, 21, 17, 24, 29),
        ),
        (
            "21 agosto 2026 12:02 hs",
            "21 agosto 2026 12:02 hs",
            datetime(2026, 8, 21, 12, 2),
        ),
    ],
)
def test_extracts_dates_used_by_attached_receipts(line, expected_value, expected_date):
    response = {"Blocks": [{"BlockType": "LINE", "Text": line}]}

    fields = extract_fields_from_wallet_lines(response)

    date_field = next(field for field in fields if field.key == "fecha")
    assert date_field.value == expected_value
    assert parse_date(date_field.value) == expected_date

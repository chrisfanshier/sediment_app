import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pyrsktools")

from utils import format_utc_datetime, parse_utc_datetime


def test_parse_with_and_without_seconds():
    assert parse_utc_datetime("2026-10-21 18:30") == datetime(2026, 10, 21, 18, 30, tzinfo=timezone.utc)
    assert parse_utc_datetime("2026-10-21T18:30:15") == datetime(2026, 10, 21, 18, 30, 15, tzinfo=timezone.utc)


def test_blank_is_none_and_invalid_raises():
    assert parse_utc_datetime("  ") is None
    with pytest.raises(ValueError):
        parse_utc_datetime("2026-13-40 99:99")


def test_format_round_trip():
    dt = datetime(2026, 10, 21, 18, 30, 15, tzinfo=timezone.utc)
    assert format_utc_datetime(dt) == "2026-10-21 18:30:15"
    assert format_utc_datetime(dt.replace(second=0)) == "2026-10-21 18:30"
    assert format_utc_datetime(None) == ""

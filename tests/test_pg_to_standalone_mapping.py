"""Unit tests for Postgres → standalone export mapping (no database required)."""
import math

from migrations.pg_to_standalone import (
    analysis_row_to_sqlite,
    deployment_datetimes,
    parse_winch_settings,
)


def test_deployment_datetimes_from_date_and_times():
    start, end = deployment_datetimes({
        "date": "2024-06-01",
        "time_launched": "10:30:00",
        "time_recovered": "11:45:00",
    })
    assert str(start).startswith("2024-06-01 10:30")
    assert str(end).startswith("2024-06-01 11:45")


def test_deployment_datetimes_handles_overnight_recovery():
    start, end = deployment_datetimes({
        "date": "2024-06-01",
        "time_launched": "23:00:00",
        "time_recovered": "01:00:00",
    })
    assert end > start


def test_analysis_row_strips_nan_flat_columns():
    flat, params = analysis_row_to_sqlite({
        "trip_index": 100,
        "result_pen_deficit": float("nan"),
        "params": {"trip": {"threshold": 0.5}},
    })
    assert flat["trip_index"] == 100
    assert flat.get("result_pen_deficit") is None
    assert params["trip"]["threshold"] == 0.5


def test_parse_winch_settings_accepts_json_string():
    assert parse_winch_settings('{"delimiter": ","}')["delimiter"] == ","


def test_parse_winch_settings_accepts_dict():
    assert parse_winch_settings({"header_lines": 3})["header_lines"] == 3

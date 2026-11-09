"""The two apps' analysis-result writers must behave the same.

sensor_standalone writes SQLite, sensor_tool writes PostgreSQL, so the two
modules cannot be one file. The behaviour the save/restore workflow depends on
still has to match, and the SQLite module is the one the rest of the suite
exercises, so this pins the Postgres module to the same contract.

Nothing here opens a database connection.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Shared API both apps' controllers call.
REQUIRED_FUNCTIONS = [
    "insert_result",
    "update_result",
    "upsert_result",
    "latest_result_id",
    "fetch_latest_result",
    "fetch_result_by_id",
    "fetch_results_for_core",
]


def _modules():
    from sensor_standalone.persistence import results_io as sqlite_io

    postgres_io = pytest.importorskip(
        "sensor_tool.persistence.analysis_results_io",
        reason="sensor_tool needs sqlalchemy and the legacy utils imports",
    )
    return sqlite_io, postgres_io


@pytest.mark.parametrize("name", REQUIRED_FUNCTIONS)
def test_both_writers_expose_the_same_api(name):
    sqlite_io, postgres_io = _modules()

    assert callable(getattr(sqlite_io, name, None)), f"sensor_standalone lacks {name}"
    assert callable(getattr(postgres_io, name, None)), f"sensor_tool lacks {name}"


@pytest.mark.parametrize("value,blank", [
    (None, True),
    (float("nan"), True),
    (float("inf"), True),
    (float("-inf"), True),
    (0.0, False),
    (0, False),
    (1.234, False),
    ("", False),
])
def test_blank_detection_agrees(value, blank):
    """A blank value must never overwrite a stored one, in either app.

    PostgreSQL will happily store NaN in a double precision column, so the
    Postgres side has to filter it for the same reason the SQLite side does,
    even though the failure mode differs (a stored NaN versus a NULL).
    """
    sqlite_io, postgres_io = _modules()

    assert sqlite_io._is_blank(value) is blank
    assert postgres_io._is_blank(value) is blank


def test_writable_flat_drops_the_same_keys():
    sqlite_io, postgres_io = _modules()

    payload = {
        "trip_index": 10,
        "result_pen_deficit": float("nan"),
        "result_seafloor": None,
        "result_recoil_max": 2.5,
    }

    assert sqlite_io._writable_flat(payload) == {
        "trip_index": 10, "result_recoil_max": 2.5,
    }
    assert postgres_io._writable_flat(payload) == {
        "trip_index": 10, "result_recoil_max": 2.5,
    }


def test_the_restore_picker_is_gone_from_both_apps():
    """Restore goes straight to the core's row; there is nothing to pick."""
    for app in ("sensor_standalone", "sensor_tool"):
        path = os.path.join(REPO_ROOT, app, "gui", "dialogs",
                            "restore_results_dialog.py")
        assert not os.path.exists(path), f"{app} still ships the picker"

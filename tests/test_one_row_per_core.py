"""Tests for the one-analysis-row-per-core storage model.

Previously each save session inserted a fresh row, so a core accumulated rows
and Restore had to ask which one to use. Now every save writes into the core's
single row, which puts the burden on the writer: a save that did not run a
given stage must leave that stage's stored values alone.
"""
import os
import sys
import tempfile
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip("PySide6")

from sensor_standalone.persistence import results_io as rio  # noqa: E402
from sensor_standalone.persistence.project import ProjectStore  # noqa: E402


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        st = ProjectStore(tmp)
        cruise_id = st.add_cruise("C", vessel_name="V")
        core_id = st.add_core(
            cruise_id, core_name="JP01", core_type="Jumbo Piston Core",
            core_length=30.0, scope=100.0,
            start_datetime="2024-01-01 09:00:00",
            end_datetime="2024-01-01 11:00:00",
            trigger_line_length=5.0, trigger_core_length=3.0,
            trigger_core_penetration=1.5,
        )
        yield st, core_id


def test_repeated_saves_reuse_one_row(store):
    st, core_id = store

    first, created = rio.upsert_result(st, core_id, {"trip_index": 10})
    assert created

    second, created_again = rio.upsert_result(st, core_id, {"trip_index": 20})

    assert not created_again
    assert second == first
    assert len(rio.fetch_results_for_core(st, core_id)) == 1
    assert rio.fetch_result_by_id(st, first)["trip_index"] == 20


def test_upsert_adopts_the_newest_row_of_a_legacy_multi_row_core(store):
    """Existing projects have several rows per core from the old behaviour.

    Those keep working: the highest result_id is the most recently inserted
    and is the row the old code restored from, so that is the one every save
    from now on updates.
    """
    st, core_id = store
    rio.insert_result(st, core_id, {"trip_index": 1})
    newest = rio.insert_result(st, core_id, {"trip_index": 2})

    target, created = rio.upsert_result(st, core_id, {"start_core_index": 99})

    assert not created
    assert target == newest
    assert rio.latest_result_id(st, core_id) == newest
    row = rio.fetch_result_by_id(st, newest)
    assert row["trip_index"] == 2, "the adopted row's own values must survive"
    assert row["start_core_index"] == 99
    # The older row is left untouched rather than deleted.
    assert len(rio.fetch_results_for_core(st, core_id)) == 2


def test_none_does_not_erase_a_stored_value(store):
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})

    rio.upsert_result(st, core_id, {"result_pen_deficit": None,
                                    "trip_index": 7})

    row = rio.fetch_result_by_id(st, rio.latest_result_id(st, core_id))
    assert row["result_pen_deficit"] == pytest.approx(1.234)
    assert row["trip_index"] == 7


def test_nan_does_not_erase_a_stored_value(store):
    """SQLite has no NaN, so a NaN result used to land as NULL.

    Calculate emits NaN for a result it cannot determine, and the save path
    only filtered None, so one inconclusive re-run wiped a good stored value.
    """
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})

    rio.upsert_result(st, core_id, {"result_pen_deficit": float("nan")})

    row = rio.fetch_result_by_id(st, rio.latest_result_id(st, core_id))
    assert row["result_pen_deficit"] == pytest.approx(1.234)


def test_rerunning_calculate_does_overwrite_with_the_new_value(store):
    """Guarding against blanks must not block a genuine update."""
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})

    rio.upsert_result(st, core_id, {"result_pen_deficit": 5.678})

    row = rio.fetch_result_by_id(st, rio.latest_result_id(st, core_id))
    assert row["result_pen_deficit"] == pytest.approx(5.678)


def test_params_sections_accumulate_across_partial_saves(store):
    """Save offsets now, calculate later: neither save may drop the other."""
    st, core_id = store

    rio.upsert_result(st, core_id, None, {"depth_offset": {"reference_sensor": "S1"}})
    rio.upsert_result(st, core_id, None, {"trip": {"threshold": 0.5}})
    rio.upsert_result(st, core_id, None, {"calc_inputs": {"trip_idx": 100}})

    params = rio.fetch_result_by_id(st, rio.latest_result_id(st, core_id))["params"]

    assert params["depth_offset"]["reference_sensor"] == "S1"
    assert params["trip"]["threshold"] == 0.5
    assert params["calc_inputs"]["trip_idx"] == 100


def test_resaving_a_section_replaces_it_wholesale(store):
    """A stage that reran owns its whole section, including cleared overrides.

    ``seafloor_manual: None`` has to be able to turn an override back off, so
    sections are replaced rather than merged key by key.
    """
    st, core_id = store
    rio.upsert_result(st, core_id, None,
                      {"calc_inputs": {"trip_idx": 100, "seafloor_manual": 20.0}})

    rio.upsert_result(st, core_id, None,
                      {"calc_inputs": {"trip_idx": 100, "seafloor_manual": None}})

    params = rio.fetch_result_by_id(st, rio.latest_result_id(st, core_id))["params"]
    assert params["calc_inputs"]["seafloor_manual"] is None


def test_update_refreshes_analyzed_at(store):
    st, core_id = store
    rid, _ = rio.upsert_result(st, core_id, {"trip_index": 1})
    original = rio.fetch_result_by_id(st, rid)["analyzed_at"]

    st._conn.execute(
        "UPDATE analysis_results SET analyzed_at = '2000-01-01 00:00:00' "
        "WHERE result_id = ?", (rid,),
    )
    st._conn.commit()

    rio.upsert_result(st, core_id, {"trip_index": 2})

    refreshed = rio.fetch_result_by_id(st, rid)["analyzed_at"]
    assert refreshed != "2000-01-01 00:00:00"
    assert refreshed >= original


def test_latest_result_id_is_none_for_an_unsaved_core(store):
    st, core_id = store
    assert rio.latest_result_id(st, core_id) is None


# ----------------------------------------------------------------------
# Save-summary staleness warning
# ----------------------------------------------------------------------

def _controller_stub(store, core_id):
    from sensor_standalone.controllers.analysis_controller import AnalysisController

    return AnalysisController, types.SimpleNamespace(
        store=store, _loaded_core_id=core_id,
        _CALC_RESULT_COLUMNS=AnalysisController._CALC_RESULT_COLUMNS,
    )


def test_partial_resave_warns_that_stored_calculations_are_stale(store):
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})
    cls, stub = _controller_stub(st, core_id)

    note = cls._stale_calc_warning(stub, ["depth offset", "trip detection"])

    assert note is not None
    assert "out of date" in note
    assert "depth offset, trip detection" in note


def test_no_warning_when_the_save_included_calculations(store):
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})
    cls, stub = _controller_stub(st, core_id)

    assert cls._stale_calc_warning(
        stub, ["depth offset", "calculations"]
    ) is None


def test_no_warning_when_nothing_was_calculated_yet(store):
    st, core_id = store
    rio.upsert_result(st, core_id, {"trip_index": 10})
    cls, stub = _controller_stub(st, core_id)

    assert cls._stale_calc_warning(stub, ["depth offset"]) is None


def test_no_warning_on_a_winch_only_save(store):
    """Winch alignment is not an input to the calculations."""
    st, core_id = store
    rio.upsert_result(st, core_id, {"result_pen_deficit": 1.234})
    cls, stub = _controller_stub(st, core_id)

    assert cls._stale_calc_warning(stub, ["winch alignment"]) is None

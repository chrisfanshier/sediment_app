import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from elog_import import match_elog_events, parse_elog_csv, resolve_positions

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "elog_export.csv")


@pytest.fixture(scope="module")
def df():
    return parse_elog_csv(FIXTURE)


def test_jpc01_matches_three_events_and_misses_deploy(df):
    m = match_elog_events(df, "JPC01")
    assert m.matched == ["bottom_utc", "pullout_utc", "recover_utc"]
    assert m.missing == ["deploy_utc"]
    assert "TESTJPC1" in [c.upper() for c in m.near_casts]
    bottom = m.candidates["bottom_utc"][0]
    assert bottom.timestamp.tzinfo is not None
    assert bottom.timestamp.strftime("%Y-%m-%d %H:%M:%S") == "2026-10-21 21:33:02"
    assert m.candidates["pullout_utc"][0].timestamp.strftime("%H:%M:%S") == "21:33:25"


def test_match_is_case_insensitive_and_trimmed(df):
    assert match_elog_events(df, "  jpc01 ").matched == ["bottom_utc", "pullout_utc", "recover_utc"]


def test_testjpc1_has_only_deploy(df):
    m = match_elog_events(df, "TestJPC1")
    assert m.matched == ["deploy_utc"]


def test_unknown_core_has_no_matches(df):
    m = match_elog_events(df, "NOPE-1")
    assert m.matched == [] and len(m.missing) == 4


def test_nan_cast_rows_never_match(df):
    assert match_elog_events(df, "NaN").matched == []


def test_core_position_uses_bottom_then_deploy(df):
    m = match_elog_events(df, "JPC01")
    sel = {f: c[0] for f, c in m.candidates.items()}
    pos = resolve_positions(sel, "core")
    assert pos == {"latitude": 64.494058, "longitude": -165.438312}
    del sel["bottom_utc"]
    assert resolve_positions(sel, "core") == {}  # no deploy either for JPC01


def test_dredge_position_start_deploy_end_recover(df):
    sel = {"deploy_utc": match_elog_events(df, "TestJPC1").candidates["deploy_utc"][0],
           "recover_utc": match_elog_events(df, "JPC01").candidates["recover_utc"][0]}
    pos = resolve_positions(sel, "dredge")
    assert pos == {"latitude": 64.494059, "longitude": -165.438311,
                   "latitude_end": 64.49406, "longitude_end": -165.438311}


def test_duplicate_actions_are_all_returned_oldest_first(tmp_path):
    f = tmp_path / "dup.csv"
    f.write_text(
        'Action,Cast,Latitude,Longitude,dateTime8601\n'
        'deploy,A1,1.0,2.0,2026-01-01T10:00:00+00:00\n'
        'deploy,A1,1.1,2.1,2026-01-01T09:00:00+00:00\n')
    m = match_elog_events(parse_elog_csv(str(f)), "A1")
    assert [c.latitude for c in m.candidates["deploy_utc"]] == [1.1, 1.0]


def test_missing_columns_raise(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        parse_elog_csv(str(f))

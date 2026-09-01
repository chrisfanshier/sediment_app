"""Headless tests for sensor_standalone project store and loaders."""
import os
import sys
import tempfile
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from sensor_standalone.persistence.project import ProjectStore
from sensor_standalone.persistence.loader import ProjectDataLoader
from sensor_standalone.persistence import results_io


def _write_staroddi(path: str):
    content = textwrap.dedent("""\
        # Star-Oddi
        1\t01.01.2024 10:00:00,000\t20,5\t100,5\t1,0\t2,0\t3,0\t0\t0
        2\t01.01.2024 10:00:01,000\t20,5\t101,0\t1,0\t2,0\t3,0\t0\t0
    """)
    with open(path, "w", encoding="latin1") as fh:
        fh.write(content)


def test_store_crud_and_loader():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProjectStore(tmp)
        cid = store.add_cruise("TestCruise", vessel_name="TestVessel")
        core_id = store.add_core(
            cid,
            core_name="JP01",
            core_type="Jumbo Piston Core",
            core_length=30.0,
            scope=100.0,
            start_datetime="2024-01-01 09:00:00",
            end_datetime="2024-01-01 11:00:00",
            trigger_line_length=5.0,
            trigger_core_length=3.0,
            trigger_core_penetration=1.5,
        )
        sensor_path = os.path.join(tmp, "ws.dat")
        _write_staroddi(sensor_path)
        store.add_sensor_file(core_id, sensor_path, sensor_location="Weight Stand", sensor_type="Star-Oddi")

        core_info = store.get_core(core_id)
        loader = ProjectDataLoader(store)
        data = loader.load_core_sensor_data(core_id, core_info)
        assert data.num_sensors >= 1
        assert "Depth" in data.depth_columns[0]

        rid = results_io.insert_result(
            store, core_id,
            flat_data={"trip_index": 10, "result_recoil_max": 2.5},
            params_section={"trip": {"threshold": 0.5}},
        )
        results_io.update_result(store, rid, params_section={"depth_offset": {"manual_offsets": {}}})
        row = results_io.fetch_result_by_id(store, rid)
        assert row["trip_index"] == 10
        assert "trip" in row["params"]
        assert "depth_offset" in row["params"]

        store.update_trigger_core_penetration(core_id, 2.0)
        assert store.get_core(core_id)["trigger_core_penetration"] == 2.0

        store.close()
        print("ok    store CRUD, loader merge, results round-trip")


if __name__ == "__main__":
    test_store_crud_and_loader()
    print("All headless tests passed.")

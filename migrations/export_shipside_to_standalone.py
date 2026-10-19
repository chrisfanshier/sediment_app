#!/usr/bin/env python3
"""Export ship-side PostgreSQL data to a portable Sensorius standalone project.

Creates a project folder the standalone app can open directly:

    ExampleProject/
        sensorius_data.sqlite
        sensor_data/<cruise>/   ← copied RSK / Star-Oddi files
        winch_data/<cruise>/      ← copied winch files

Typical use on the ship (or any machine with the postgres DB and data files):

    python migrations/export_shipside_to_standalone.py \\
        --output ./ExampleProject \\
        --cruise-name "SKQ2024" \\
        --file-root "C:/shipsideDB"

List cruises without exporting:

    python migrations/export_shipside_to_standalone.py --list-cruises

Environment overrides (optional):

    SENSORIUS_PG_URL      PostgreSQL URL (instead of db_util.DB_URL)
    FILE_STORAGE_ROOT     Root directory for sensor/winch files on disk
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402

from migrations.pg_to_standalone import (  # noqa: E402
    analysis_row_to_sqlite,
    deployment_datetimes,
    parse_winch_settings,
    pg_file_path,
    row_mapping,
)
from sensor_standalone.persistence import results_io  # noqa: E402
from sensor_standalone.persistence.project import ProjectStore, _iso  # noqa: E402

logger = logging.getLogger(__name__)

CORES_QUERY = """
    SELECT
        c.*,
        ct.core_type_name,
        w.wire_type AS wire_type_name
    FROM cores c
    LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
    LEFT JOIN wire w ON c.wire_type_id = w.wire_type_id
    WHERE c.cruise_id = :cid
      AND EXISTS (
          SELECT 1 FROM sensor_files sf WHERE sf.core_id = c.core_id
      )
    ORDER BY c.core_name
"""

CRUISES_QUERY = """
    SELECT cr.cruise_id, cr.cruise_name, v.vessel_name,
           (SELECT COUNT(*) FROM cores c
            WHERE c.cruise_id = cr.cruise_id
              AND EXISTS (SELECT 1 FROM sensor_files sf WHERE sf.core_id = c.core_id)
           ) AS cores_with_sensor
    FROM cruises cr
    LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
    ORDER BY cr.cruise_name
"""


@contextmanager
def pg_connection(postgres_url: Optional[str]) -> Iterator:
    if postgres_url:
        engine = create_engine(postgres_url)
        with engine.connect() as conn:
            yield conn
    else:
        from db_util import get_connection  # noqa: WPS433

        with get_connection() as conn:
            yield conn


def list_cruises(conn) -> list[dict]:
    rows = conn.execute(text(CRUISES_QUERY)).fetchall()
    return [row_mapping(r) for r in rows]


def resolve_cruise_ids(
    conn,
    cruise_ids: list[int],
    cruise_names: list[str],
) -> list[int]:
    if cruise_ids:
        return cruise_ids
    all_cruises = list_cruises(conn)
    if not cruise_names:
        return [c["cruise_id"] for c in all_cruises if c["cores_with_sensor"]]
    name_map = {c["cruise_name"].lower(): c["cruise_id"] for c in all_cruises}
    resolved = []
    for name in cruise_names:
        cid = name_map.get(name.lower())
        if cid is None:
            raise SystemExit(f"Cruise not found: {name!r}")
        resolved.append(cid)
    return resolved


def fetch_cores(conn, cruise_id: int) -> list[dict]:
    rows = conn.execute(text(CORES_QUERY), {"cid": cruise_id}).fetchall()
    return [row_mapping(r) for r in rows]


def fetch_sensor_files(conn, core_id: int) -> list[dict]:
    rows = conn.execute(
        text("""
            SELECT file_id, file_name, file_path,
                   sensor_type, sensor_location, remarks
            FROM sensor_files
            WHERE core_id = :cid
            ORDER BY file_name
        """),
        {"cid": core_id},
    ).fetchall()
    return [row_mapping(r) for r in rows]


def fetch_winch_files(conn, cruise_id: int) -> list[dict]:
    rows = conn.execute(
        text("""
            SELECT winch_file_id, file_name, file_path,
                   start_time, end_time, settings, notes
            FROM winch_data
            WHERE cruise_id = :cid
            ORDER BY file_name
        """),
        {"cid": cruise_id},
    ).fetchall()
    return [row_mapping(r) for r in rows]


def fetch_latest_analysis(conn, core_id: int) -> Optional[dict]:
    """One row per core: highest result_id (same rule as standalone upsert)."""
    row = conn.execute(
        text("""
            SELECT *
            FROM sensor_analysis_results
            WHERE core_id = :cid
            ORDER BY result_id DESC
            LIMIT 1
        """),
        {"cid": core_id},
    ).fetchone()
    return None if row is None else row_mapping(row)


def export_sensor_file(
    store: ProjectStore,
    new_core_id: int,
    sf: dict,
    file_root: str,
    dry_run: bool,
) -> bool:
    src = pg_file_path(sf["file_path"], sf["file_name"], file_root)
    if not os.path.isfile(src):
        logger.warning("  missing sensor file: %s", src)
        return False
    if dry_run:
        logger.info("  would copy sensor %s", sf["file_name"])
        return True
    store.add_sensor_file(
        new_core_id,
        src,
        sensor_location=sf.get("sensor_location"),
        sensor_type=sf.get("sensor_type"),
        remarks=sf.get("remarks"),
    )
    return True


def export_winch_file(
    store: ProjectStore,
    cruise_id: int,
    wf: dict,
    file_root: str,
    dry_run: bool,
) -> bool:
    src = pg_file_path(wf["file_path"], wf["file_name"], file_root)
    if not os.path.isfile(src):
        logger.warning("  missing winch file: %s", src)
        return False
    settings = parse_winch_settings(wf.get("settings"))
    if dry_run:
        logger.info("  would copy winch %s", wf["file_name"])
        return True
    store.add_winch_file(
        cruise_id,
        src,
        settings=settings,
        start_time=wf.get("start_time"),
        end_time=wf.get("end_time"),
        notes=wf.get("notes"),
    )
    return True


def export_analysis(
    store: ProjectStore,
    new_core_id: int,
    pg_row: dict,
    dry_run: bool,
) -> bool:
    flat, params = analysis_row_to_sqlite(pg_row)
    if dry_run:
        logger.info(
            "  would save analysis (trip=%s, pen_deficit=%s)",
            flat.get("trip_index"), flat.get("result_pen_deficit"),
        )
        return True
    rid, _ = results_io.upsert_result(store, new_core_id, flat, params)
    analyzed_at = pg_row.get("analyzed_at")
    if analyzed_at is not None:
        store._conn.execute(  # noqa: SLF001
            "UPDATE analysis_results SET analyzed_at = ? WHERE result_id = ?",
            (_iso(analyzed_at), rid),
        )
        store._conn.commit()
    return True


def verify_project(store: ProjectStore, core_ids: list[int]) -> list[str]:
    """Try loading each exported core through the standalone loader."""
    from sensor_standalone.persistence.loader import ProjectDataLoader

    loader = ProjectDataLoader(store)
    failures = []
    for core_id in core_ids:
        info = store.get_core(core_id)
        if info is None:
            failures.append(f"core_id {core_id}: not in store")
            continue
        try:
            sd = loader.load_core_sensor_data(core_id, info)
            logger.info(
                "  verified %s: %s rows, %s depth cols",
                info["core_name"], f"{sd.row_count:,}", len(sd.depth_columns),
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{info.get('core_name', core_id)}: {exc}")
    return failures


def export_cruise(
    conn,
    store: ProjectStore,
    pg_cruise_id: int,
    file_root: str,
    *,
    include_winch: bool,
    include_analysis: bool,
    dry_run: bool,
) -> dict:
    cruise_row = conn.execute(
        text("""
            SELECT cr.cruise_id, cr.cruise_name, v.vessel_name
            FROM cruises cr
            LEFT JOIN vessels v ON cr.vessel_id = v.vessel_id
            WHERE cr.cruise_id = :cid
        """),
        {"cid": pg_cruise_id},
    ).fetchone()
    if cruise_row is None:
        raise ValueError(f"Unknown cruise_id {pg_cruise_id}")
    cruise = row_mapping(cruise_row)

    logger.info(
        "Cruise %s (%s)",
        cruise["cruise_name"], cruise.get("vessel_name") or "no vessel",
    )

    stats = {
        "cores": 0, "sensor_files": 0, "winch_files": 0,
        "analysis_rows": 0, "missing_files": 0,
    }
    exported_core_ids: list[int] = []

    if dry_run:
        new_cruise_id = pg_cruise_id
    else:
        new_cruise_id = store.add_cruise(
            cruise["cruise_name"],
            vessel_name=cruise.get("vessel_name"),
        )

    cores = fetch_cores(conn, pg_cruise_id)
    for core in cores:
        start_dt, end_dt = deployment_datetimes(core)
        logger.info("  Core %s", core["core_name"])

        if dry_run:
            new_core_id = core["core_id"]
        else:
            new_core_id = store.add_core(
                new_cruise_id,
                core_name=core["core_name"],
                core_type=core.get("core_type_name"),
                core_length=core.get("core_length"),
                scope=core.get("scope"),
                start_datetime=start_dt,
                end_datetime=end_dt,
                trigger_line_length=core.get("trigger_line_length"),
                trigger_core_length=core.get("trigger_core_length"),
                trigger_core_penetration=core.get("trigger_core_penetration"),
                trigger_core_recovery=core.get("trigger_core_recovery"),
                piston_core_recovery=core.get("piston_core_recovery"),
                pig_weights=core.get("pig_weights"),
                wire_type=core.get("wire_type_name") or core.get("wire_type"),
                notes=core.get("notes"),
            )
        stats["cores"] += 1
        exported_core_ids.append(new_core_id)

        for sf in fetch_sensor_files(conn, core["core_id"]):
            ok = export_sensor_file(store, new_core_id, sf, file_root, dry_run)
            if ok:
                stats["sensor_files"] += 1
            else:
                stats["missing_files"] += 1

        if include_analysis:
            analysis = fetch_latest_analysis(conn, core["core_id"])
            if analysis is not None:
                if export_analysis(store, new_core_id, analysis, dry_run):
                    stats["analysis_rows"] += 1

    if include_winch:
        for wf in fetch_winch_files(conn, pg_cruise_id):
            ok = export_winch_file(store, new_cruise_id, wf, file_root, dry_run)
            if ok:
                stats["winch_files"] += 1
            else:
                stats["missing_files"] += 1

    stats["exported_core_ids"] = exported_core_ids
    return stats


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export ship-side PostgreSQL to a standalone Sensorius project folder.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Destination project folder (created if needed).",
    )
    parser.add_argument(
        "--cruise-id", type=int, action="append", default=[],
        help="Postgres cruise_id to export (repeatable). Default: all with sensor cores.",
    )
    parser.add_argument(
        "--cruise-name", action="append", default=[],
        help="Postgres cruise_name to export (repeatable).",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.environ.get("SENSORIUS_PG_URL"),
        help="PostgreSQL URL. Default: db_util.DB_URL or SENSORIUS_PG_URL env.",
    )
    parser.add_argument(
        "--file-root",
        default=os.environ.get("FILE_STORAGE_ROOT"),
        help="Root directory for sensor/winch files (config.FILE_STORAGE_ROOT).",
    )
    parser.add_argument(
        "--skip-winch", action="store_true",
        help="Do not copy winch files.",
    )
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="Do not copy saved analysis results.",
    )
    parser.add_argument(
        "--list-cruises", action="store_true",
        help="Print cruises with sensor data and exit.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be copied without writing files.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="After export, load each core through ProjectDataLoader.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    with pg_connection(args.postgres_url) as conn:
        if args.list_cruises:
            for c in list_cruises(conn):
                print(
                    f"{c['cruise_id']:>5}  {c['cruise_name']:<30}  "
                    f"{c.get('vessel_name') or '':<20}  "
                    f"{c['cores_with_sensor']} cores w/ sensor"
                )
            return 0

        if not args.output:
            parser.error("--output is required unless --list-cruises is set")

        if not args.file_root:
            try:
                from config import ROOT_DIRECTORY  # noqa: WPS433
                args.file_root = ROOT_DIRECTORY
            except ImportError:
                parser.error(
                    "Set --file-root or FILE_STORAGE_ROOT to the directory "
                    "that contains Sensor_Data/, winch_data/, etc."
                )

        file_root = os.path.abspath(args.file_root)
        if not os.path.isdir(file_root):
            parser.error(f"File root not found: {file_root}")

        cruise_ids = resolve_cruise_ids(conn, args.cruise_id, args.cruise_name)
        if not cruise_ids:
            logger.error("No cruises matched.")
            return 1

        if args.dry_run:
            store = None
            logger.info("DRY RUN — no files will be written")
        else:
            out = Path(args.output).resolve()
            if out.exists() and any(out.iterdir()):
                logger.warning("Output folder is not empty: %s", out)
            store = ProjectStore(out)
            logger.info("Writing project to %s", out)

        totals = {
            "cores": 0, "sensor_files": 0, "winch_files": 0,
            "analysis_rows": 0, "missing_files": 0,
        }
        all_core_ids: list[int] = []

        for cid in cruise_ids:
            stats = export_cruise(
                conn, store, cid, file_root,
                include_winch=not args.skip_winch,
                include_analysis=not args.skip_analysis,
                dry_run=args.dry_run,
            )
            for key in totals:
                totals[key] += stats.get(key, 0)
            all_core_ids.extend(stats.get("exported_core_ids", []))

        logger.info(
            "Done — %s cores, %s sensor files, %s winch files, "
            "%s analysis rows (%s missing files on disk)",
            totals["cores"], totals["sensor_files"], totals["winch_files"],
            totals["analysis_rows"], totals["missing_files"],
        )

        if args.verify and store is not None and all_core_ids:
            logger.info("Verifying exported cores…")
            failures = verify_project(store, all_core_ids)
            if failures:
                for msg in failures:
                    logger.error("  verify failed: %s", msg)
                return 1

        if store is not None:
            store.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

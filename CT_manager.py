import os
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import time
import shutil

# === Shared utilities ===
# Uses the network branch db_util.py and config.py (sediment_cores database)
from db_util import get_connection
from config import get_full_path, ROOT_DIRECTORY

# === Database Setup ===
# sediment_cores is the permanent network database
engine = create_engine("postgresql+psycopg2://postgres:madmaxfuryroad@localhost:5432/sediment_cores")

# === XML Parsing ===
def parse_ct_xml(xml_path):
    """Extracts metadata from XML"""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        root_tag = root.tag

        def get_text(*tags):
            for tag in tags:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    return el.text.strip()
            # Fallback: namespace-agnostic + case-insensitive
            tags_lower = {t.lower() for t in tags}
            for elem in root.iter():
                local = elem.tag.rsplit('}', 1)[-1] if '}' in elem.tag else elem.tag
                if local.lower() in tags_lower and elem.text and elem.text.strip():
                    return elem.text.strip()
            return None

        section_id = get_text("Section-ID", "section-id", "sectionID")
        if not section_id:
            section_id = get_text("Section-Number", "section-number")

        core_name = get_text("Core-ID", "coreID", "core-id")
        if core_name:
            core_name = core_name.strip().replace("_", "-").upper()

        if not core_name:
            filename = os.path.basename(xml_path)
            import re as _re
            corrected_match = _re.match(r'^(.+?)_corrected(\.[^.]+)$', filename, _re.IGNORECASE)
            if corrected_match:
                sibling_name = corrected_match.group(1) + corrected_match.group(2)
                sibling_path = os.path.join(os.path.dirname(xml_path), sibling_name)
                if os.path.exists(sibling_path):
                    try:
                        sibling_tree = ET.parse(sibling_path)
                        sibling_root = sibling_tree.getroot()

                        def get_sibling_text(*tags):
                            for tag in tags:
                                el = sibling_root.find(f".//{tag}")
                                if el is not None and el.text:
                                    return el.text.strip()
                            return None

                        sibling_core = get_sibling_text("Core-ID", "coreID", "core-id")
                        if sibling_core:
                            core_name = sibling_core.strip().replace("_", "-").upper()

                        if not section_id:
                            section_id = get_sibling_text("Section-ID", "section-id", "sectionID") \
                                      or get_sibling_text("Section-Number", "section-number")

                        del sibling_tree
                        print(f"ℹ️ Used sibling XML for core-id: {sibling_name} → {core_name}")
                    except Exception as e:
                        print(f"Warning: could not parse sibling XML {sibling_path}: {e}")

        total_scanned_length = get_text("Total-Scanned-Length", "total-scanned-length")

        data = {
            "core_name": core_name,
            "scan_id": get_text("Scan-ID", "scanID", "scan-id"),
            "section_id": section_id,
            "image_type": get_text("Image-Type", "image-type"),
            "processing_stage": get_text("Processing-Stage", "processing-stage"),
            "section_number": section_id,
            "xml_root_tag": root_tag,
            "total_scanned_length": total_scanned_length,
            "tif_filename": get_text("filename", "Filename", "file-name"),
        }

        del tree
        return data
    except Exception as e:
        print(f"Error parsing {xml_path}: {e}")
        return None


# === File Manager Class ===
class CTFileManager:
    def __init__(self, ct_root):
        self.ct_root = ct_root

    def edit_xml_field(self, xml_path, field_name, new_value):
        full_path = xml_path if os.path.isabs(xml_path) else get_full_path(xml_path)

        try:
            if not os.path.exists(full_path):
                print(f"File not found: {full_path}")
                return False

            tree = ET.parse(full_path)
            root = tree.getroot()

            possible_tags = [field_name]
            if field_name == "Core-ID":
                possible_tags.extend(["coreID", "core-id", "CoreID", "COREID"])
            elif field_name == "Section-ID":
                possible_tags.extend(["sectionID", "section-id", "SectionID", "SECTIONID"])
            elif field_name == "Section-Number":
                possible_tags.extend(["section-number", "sectionNumber", "SectionNumber"])

            found = False
            updated_tag = None
            old_value = None

            for elem in root.iter():
                if any(elem.tag.lower() == tag.lower() for tag in possible_tags):
                    old_value = elem.text
                    elem.text = new_value
                    found = True
                    updated_tag = elem.tag
                    break

            if found:
                temp_path = full_path + ".tmp"
                tree.write(temp_path, encoding='utf-8', xml_declaration=True)
                del tree
                time.sleep(0.05)
                shutil.move(temp_path, full_path)
                print(f"Updated {updated_tag}: '{old_value}' → '{new_value}' in {os.path.basename(full_path)}")
                return True
            else:
                del tree
                print(f"Field '{field_name}' not found in {os.path.basename(full_path)}")
                return False

        except Exception as e:
            print(f"Error editing XML {full_path}: {e}")
            temp_path = full_path + ".tmp"
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return False


# === PHASE 1: Scan & Validate ===
def get_folder_size(folder):
    total = 0
    for dirpath, _, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def resolve_tif_filename(xml_path, meta_tif_filename):
    xml_basename = os.path.basename(xml_path)
    xml_stem = os.path.splitext(xml_basename)[0]
    return xml_stem + ".tif"


def resolve_tif_info(meta, xml_path, folder):
    root_tag = meta.get("xml_root_tag", "")
    processing_stage = (meta.get("processing_stage") or "").lower()
    tif_filename = None
    tif_filesize_bytes = None

    def get_tif_size(filename):
        tif_path = os.path.join(folder, filename)
        if os.path.exists(tif_path):
            try:
                return filename, os.path.getsize(tif_path)
            except OSError:
                return filename, None
        tag_name = meta.get("tif_filename")
        if tag_name and tag_name != filename:
            tag_path = os.path.join(folder, tag_name)
            if os.path.exists(tag_path):
                try:
                    return tag_name, os.path.getsize(tag_path)
                except OSError:
                    return tag_name, None
        print(f"⚠️ TIF not found on disk: {tif_path}")
        return filename, None

    if root_tag == "geotek-image":
        derived = resolve_tif_filename(xml_path, meta.get("tif_filename"))
        tif_filename, tif_filesize_bytes = get_tif_size(derived)

    elif root_tag == "geotek-xray-scan-recipe":
        tif_filename = None
        tif_filesize_bytes = None

    elif root_tag in ("geotek-ct-stack", "geotek-ct-recon"):
        acquired_stages = ("acquired",)
        recon_stages = ("recon", "reconstructed")

        if processing_stage in acquired_stages:
            tif_filename = None
            tif_filesize_bytes = get_folder_size(folder)
        elif any(s in processing_stage for s in recon_stages) or processing_stage == "":
            xml_count = sum(1 for f in os.listdir(folder) if f.lower().endswith(".xml"))
            if xml_count > 1:
                derived = resolve_tif_filename(xml_path, meta.get("tif_filename"))
                tif_filename, tif_filesize_bytes = get_tif_size(derived)
            else:
                tif_filename = None
                tif_filesize_bytes = get_folder_size(folder)

    return tif_filename, tif_filesize_bytes


def scan_ct_folders(ct_root):
    found = []
    for root, dirs, files in os.walk(ct_root):
        xmls = [f for f in files if f.lower().endswith(".xml")]
        for xml_file in xmls:
            xml_path = os.path.join(root, xml_file)
            meta = parse_ct_xml(xml_path)
            if meta and meta["core_name"]:
                tif_filename, tif_filesize_bytes = resolve_tif_info(meta, xml_path, root)
                record = {
                    **meta,
                    "xml_path": os.path.relpath(xml_path, ROOT_DIRECTORY),
                    "tiff_folder": os.path.relpath(root, ROOT_DIRECTORY),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "tif_filename": tif_filename,
                    "tif_filesize_bytes": tif_filesize_bytes,
                }
                found.append(record)
            else:
                tag = meta.get("xml_root_tag", "unknown") if meta else "N/A"
                print(f"\u26a0\ufe0f Skipped (no core_name): {xml_file} [root_tag={tag}, folder={root}]")
    if len(found) == 0:
        print(f"\u26a0\ufe0f No XML files with core_name found in {ct_root}")
    return found


def validate_against_database(records):
    validated_records = []

    for record in records:
        validation = {
            "record": record,
            "core_exists": False,
            "section_exists": False,
            "issues": [],
            "status": "unknown"
        }

        with get_connection() as conn:
            core_row = conn.execute(
                text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                {"core_name": record["core_name"].strip()}
            ).fetchone()

            if not core_row:
                validation["issues"].append("Core not in database")
                validation["status"] = "invalid"
            else:
                validation["core_exists"] = True
                core_id = core_row[0]

                try:
                    section_number_int = int(record["section_number"])
                    section_row = conn.execute(
                        text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                        {"core_id": core_id, "section_number": section_number_int}
                    ).fetchone()

                    if not section_row:
                        validation["issues"].append("Section not in database")
                        validation["status"] = "invalid"
                    else:
                        validation["section_exists"] = True
                        validation["status"] = "valid"

                except (TypeError, ValueError):
                    validation["issues"].append("Invalid section number format")
                    validation["status"] = "invalid"

        validated_records.append(validation)

    return validated_records


def get_validation_summary(validated_records):
    if not validated_records:
        return pd.DataFrame(), {}

    summary_data = {}

    for val in validated_records:
        record = val["record"]
        key = (record["core_name"], record["section_number"])

        if key not in summary_data:
            summary_data[key] = {
                "Core": record["core_name"],
                "Section": record["section_number"],
                "XML Count": 0,
                "Status": "✅ Valid" if val["status"] == "valid" else "❌ Invalid",
                "Issues": "; ".join(val["issues"]) if val["issues"] else "",
                "records": []
            }

        summary_data[key]["XML Count"] += 1
        summary_data[key]["records"].append(val)

        if val["status"] == "invalid":
            summary_data[key]["Status"] = "❌ Invalid"
            if val["issues"]:
                current_issues = set(summary_data[key]["Issues"].split("; ")) if summary_data[key]["Issues"] else set()
                current_issues.update(val["issues"])
                summary_data[key]["Issues"] = "; ".join(current_issues)

    df = pd.DataFrame([
        {k: v for k, v in item.items() if k != "records"}
        for item in summary_data.values()
    ])

    if not df.empty:
        df = df.sort_values(["Core", "Section"])

    return df, summary_data


# === PHASE 2: Import Directly to Database ===
def import_to_database(validated_records):
    saved_count = 0
    skipped_by_path = 0
    skipped_by_fingerprint = 0
    failed_count = 0

    with engine.begin() as conn:
        existing_paths = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml"))
        )

        existing_fingerprints = set()
        result = conn.execute(text("""
            SELECT
                core_name,
                section_number,
                xml_root_tag,
                COALESCE(image_type, '') as image_type,
                COALESCE(processing_stage, '') as processing_stage,
                xml_path,
                tiff_folder
            FROM ct_xml
        """))
        for row in result:
            db_record = {
                "core_name": row[0],
                "section_number": str(row[1]),
                "xml_root_tag": row[2],
                "image_type": row[3],
                "processing_stage": row[4],
                "xml_path": row[5] or "",
                "tiff_folder": row[6] or "",
            }
            fp = create_xml_fingerprint(db_record)
            existing_fingerprints.add(fingerprint_to_string(fp))

        for val in validated_records:
            if val["status"] != "valid":
                failed_count += 1
                continue

            record = val["record"]

            if record["xml_path"] in existing_paths:
                skipped_by_path += 1
                continue

            fp = create_xml_fingerprint(record)
            fp_string = fingerprint_to_string(fp)

            if fp_string in existing_fingerprints:
                print(f"⚠️ Skipping duplicate fingerprint: {record['core_name']}-{record['section_number']} {record['xml_root_tag']} {os.path.basename(record['xml_path'])}")
                skipped_by_fingerprint += 1
                continue

            try:
                core_row = conn.execute(
                    text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                    {"core_name": record["core_name"].strip()}
                ).fetchone()
                core_id = core_row[0]

                section_number_int = int(record["section_number"])
                section_row = conn.execute(
                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                    {"core_id": core_id, "section_number": section_number_int}
                ).fetchone()
                section_id = section_row[0]

                conn.execute(
                    text("""
                        INSERT INTO ct_xml (
                            core_id, core_name, section_id, scan_id, image_type,
                            processing_stage, section_number,
                            xml_path, tiff_folder, xml_root_tag, timestamp,
                            tif_filename, tif_filesize_bytes
                        ) VALUES (
                            :core_id, :core_name, :section_id, :scan_id, :image_type,
                            :processing_stage, :section_number,
                            :xml_path, :tiff_folder, :xml_root_tag, :timestamp,
                            :tif_filename, :tif_filesize_bytes
                        )
                    """),
                    dict(
                        core_id=core_id,
                        core_name=record["core_name"],
                        section_id=section_id,
                        scan_id=record["scan_id"],
                        image_type=record["image_type"],
                        processing_stage=record["processing_stage"],
                        section_number=record["section_number"],
                        xml_path=record["xml_path"],
                        tiff_folder=record["tiff_folder"],
                        xml_root_tag=record["xml_root_tag"],
                        timestamp=record["timestamp"],
                        tif_filename=record.get("tif_filename"),
                        tif_filesize_bytes=record.get("tif_filesize_bytes"),
                    )
                )
                saved_count += 1

            except Exception as e:
                print(f"❌ Error importing {record['xml_path']}: {e}")
                failed_count += 1

    if skipped_by_path > 0:
        print(f"ℹ️ Skipped {skipped_by_path} records (path already exists)")
    if skipped_by_fingerprint > 0:
        print(f"ℹ️ Skipped {skipped_by_fingerprint} records (fingerprint already exists)")

    return saved_count, skipped_by_path, skipped_by_fingerprint, failed_count


# === PHASE 3: View ct_xml table ===
def get_ct_xml_summary():
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT core_name, section_number, xml_root_tag, image_type, processing_stage
            FROM ct_xml
            ORDER BY core_name, section_number
        """))
        rows = [dict(row._mapping) for row in result.fetchall()]

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    directory_types = ["CT-Volume", "Helical", "Laminography"]
    image_types = ["giXRayImage", "giCTOrthogonalView"]

    summary_rows = []
    all_pairs = df[["core_name", "section_number"]].drop_duplicates()

    for _, row in all_pairs.iterrows():
        core = row["core_name"]
        section = row["section_number"]
        subdf = df[(df["core_name"] == core) & (df["section_number"] == section)]
        xml_count = len(subdf)

        ct_scan_records = subdf[subdf["xml_root_tag"].isin(["geotek-ct-stack", "geotek-ct-recon"])]
        directories = []
        for dtype in directory_types:
            stages = ct_scan_records.loc[ct_scan_records["image_type"] == dtype, "processing_stage"].dropna().unique()
            if len(stages) > 0:
                directories.append(f"{dtype} ({', '.join(sorted(stages))})")
        directories_str = "; ".join(directories) if directories else ""

        image_records = subdf[subdf["xml_root_tag"] == "geotek-image"]
        images = [itype for itype in image_types if (image_records["image_type"] == itype).any()]
        images_str = ", ".join(images) if images else ""

        summary_rows.append({
            "Core": core,
            "Section": section,
            "Total XMLs": xml_count,
            "CT/Scan Types": directories_str,
            "Image Types": images_str
        })

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(["Core", "Section"])
    return summary


# === PHASE 4: Path Updates ===
def verify_xml_paths(ct_root):
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT id, core_name, section_number, xml_root_tag,
                   image_type, processing_stage, xml_path, tiff_folder
            FROM ct_xml
            ORDER BY core_name, section_number
        """))
        db_records = [dict(row._mapping) for row in result.fetchall()]

    results = {"exists": [], "missing": [], "total": len(db_records)}
    for record in db_records:
        if os.path.exists(get_full_path(record["xml_path"])):
            results["exists"].append(record)
        else:
            results["missing"].append(record)
    return results


def _fingerprint_parent_folder(tiff_folder):
    """Recon parent folder (e.g. Recon vs 3_Helical_Scan_Recon), not leaf (e.g. Orthogonal)."""
    path = (tiff_folder or "").rstrip(os.sep)
    if not path:
        return ""
    return os.path.basename(os.path.dirname(path))


def create_xml_fingerprint(record):
    xml_filename = os.path.basename(record["xml_path"])
    if record["xml_root_tag"] == "geotek-ct-stack":
        parent_folder = _fingerprint_parent_folder(record["tiff_folder"])
        return {
            "core_name": record["core_name"],
            "section_number": str(record["section_number"]),
            "xml_root_tag": record["xml_root_tag"],
            "image_type": record.get("image_type", ""),
            "processing_stage": record.get("processing_stage", ""),
            "parent_folder": parent_folder,
            "xml_filename": xml_filename
        }
    elif record["xml_root_tag"] == "geotek-image":
        parent_folder = _fingerprint_parent_folder(record["tiff_folder"])
        return {
            "core_name": record["core_name"],
            "section_number": str(record["section_number"]),
            "xml_root_tag": record["xml_root_tag"],
            "image_type": record.get("image_type", ""),
            "parent_folder": parent_folder,
            "xml_filename": xml_filename
        }
    else:
        parent_folder = os.path.basename(record["tiff_folder"])
        return {
            "core_name": record["core_name"],
            "section_number": str(record["section_number"]),
            "xml_root_tag": record["xml_root_tag"],
            "parent_folder": parent_folder,
            "xml_filename": xml_filename
        }


def fingerprint_to_string(fp):
    parts = [
        fp["core_name"], fp["section_number"], fp["xml_root_tag"],
        fp.get("image_type", ""), fp.get("processing_stage", ""),
        fp.get("parent_folder", ""), fp["xml_filename"]
    ]
    return "|".join(str(p) for p in parts)


def find_moved_files(ct_root, missing_records):
    missing_fingerprints = {}
    for record in missing_records:
        fp = create_xml_fingerprint(record)
        fp_string = fingerprint_to_string(fp)
        missing_fingerprints[fp_string] = record

    st.write(f"🔍 Scanning {ct_root} for XML files...")
    disk_records = scan_ct_folders(ct_root)

    matches = []
    not_found = []

    for missing_fp_string, db_record in missing_fingerprints.items():
        found = False
        for disk_record in disk_records:
            disk_fp = create_xml_fingerprint(disk_record)
            if missing_fp_string == fingerprint_to_string(disk_fp):
                matches.append({
                    "id": db_record["id"],
                    "core_name": db_record["core_name"],
                    "section_number": db_record["section_number"],
                    "xml_root_tag": db_record["xml_root_tag"],
                    "old_xml_path": db_record["xml_path"],
                    "new_xml_path": disk_record["xml_path"],
                    "old_tiff_folder": db_record["tiff_folder"],
                    "new_tiff_folder": disk_record["tiff_folder"],
                    "fingerprint": disk_fp
                })
                found = True
                break
        if not found:
            not_found.append(db_record)

    return {"matches": matches, "not_found": not_found}


def update_xml_paths(updates):
    updated_count = 0
    skipped_count = 0

    with engine.begin() as conn:
        for update in updates:
            existing = conn.execute(text("""
                SELECT id FROM ct_xml
                WHERE xml_path = :new_path AND id != :current_id
            """), {"new_path": update["new_xml_path"], "current_id": update["id"]}).fetchone()

            if existing:
                print(f"⚠️ Skipping update for ID {update['id']}: target path already exists")
                skipped_count += 1
                continue

            try:
                conn.execute(text("""
                    UPDATE ct_xml SET xml_path = :new_xml_path, tiff_folder = :new_tiff_folder
                    WHERE id = :id
                """), {
                    "id": update["id"],
                    "new_xml_path": update["new_xml_path"],
                    "new_tiff_folder": update["new_tiff_folder"]
                })
                updated_count += 1
            except Exception as e:
                print(f"❌ Error updating ID {update['id']}: {e}")
                skipped_count += 1

    return updated_count, skipped_count


# === PHASE 5: Export helpers ===

def get_cruises_from_db():
    """Return list of (cruise_id, cruise_name) tuples that have CT data."""
    with get_connection() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT cr.cruise_id, cr.cruise_name
            FROM cruises cr
            JOIN cores c ON c.cruise_id = cr.cruise_id
            JOIN ct_xml x ON x.core_name = c.core_name
            ORDER BY cr.cruise_name
        """))
        return [(row[0], row[1]) for row in result.fetchall()]


def get_cores_for_cruises(cruise_ids):
    """Return core names belonging to the given cruise_ids that have CT data."""
    if not cruise_ids:
        return []
    with get_connection() as conn:
        placeholders = ", ".join(f":cid_{i}" for i in range(len(cruise_ids)))
        params = {f"cid_{i}": cid for i, cid in enumerate(cruise_ids)}
        result = conn.execute(
            text(f"""
                SELECT DISTINCT c.core_name
                FROM cores c
                JOIN ct_xml x ON x.core_name = c.core_name
                WHERE c.cruise_id IN ({placeholders})
                ORDER BY c.core_name
            """),
            params
        )
        return [row[0] for row in result.fetchall()]


def get_cores_from_db():
    with get_connection() as conn:
        result = conn.execute(text("SELECT core_name FROM cores ORDER BY core_name"))
        return [row[0] for row in result.fetchall()]


def get_sections_for_cores(core_names):
    if not core_names:
        return []
    with get_connection() as conn:
        placeholders = ", ".join(f":core_{i}" for i in range(len(core_names)))
        params = {f"core_{i}": name for i, name in enumerate(core_names)}
        result = conn.execute(
            text(f"""
                SELECT DISTINCT core_name, section_number
                FROM ct_xml
                WHERE core_name IN ({placeholders})
                ORDER BY core_name, section_number
            """),
            params
        )
        return [(row[0], str(row[1])) for row in result.fetchall()]


def get_tiff_folders_for_export(core_names, section_numbers, image_type):
    if not core_names or not section_numbers:
        return []
    with get_connection() as conn:
        core_placeholders = ", ".join(f":core_{i}" for i in range(len(core_names)))
        section_placeholders = ", ".join(f":sec_{i}" for i in range(len(section_numbers)))
        params = {f"core_{i}": name for i, name in enumerate(core_names)}
        params.update({f"sec_{i}": str(s) for i, s in enumerate(section_numbers)})
        result = conn.execute(
            text(f"""
                SELECT core_name, section_number, tiff_folder, tif_filename, xml_path
                FROM ct_xml
                WHERE image_type = :image_type
                  AND core_name IN ({core_placeholders})
                  AND CAST(section_number AS TEXT) IN ({section_placeholders})
            """),
            {"image_type": image_type, **params}
        )
        return [dict(row._mapping) for row in result.fetchall()]


# CHANGED: added id to SELECT so we can trace rows in the export log
def get_all_tiff_folders_for_sections(core_names, section_numbers):
    if not core_names or not section_numbers:
        return []
    with get_connection() as conn:
        core_placeholders = ", ".join(f":core_{i}" for i in range(len(core_names)))
        section_placeholders = ", ".join(f":sec_{i}" for i in range(len(section_numbers)))
        params = {f"core_{i}": name for i, name in enumerate(core_names)}
        params.update({f"sec_{i}": str(s) for i, s in enumerate(section_numbers)})
        result = conn.execute(
            text(f"""
                SELECT DISTINCT id, core_name, section_number, tiff_folder,
                       xml_root_tag, processing_stage, image_type, xml_path
                FROM ct_xml
                WHERE core_name IN ({core_placeholders})
                  AND CAST(section_number AS TEXT) IN ({section_placeholders})
            """),
            params
        )
        return [dict(row._mapping) for row in result.fetchall()]


def is_recon_stack(row):
    root_tag = (row.get("xml_root_tag") or "").lower()
    stage = (row.get("processing_stage") or "").lower()
    xml_path = (row.get("xml_path") or "")
    xml_filename = os.path.basename(xml_path).lower()
    return (
        root_tag in ("geotek-ct-stack", "geotek-ct-recon")
        and ("recon" in stage or "reconstructed" in stage)
        and xml_filename == "index.xml"
    )


def find_corrected_tifs(tiff_folder):
    matches = []
    if not os.path.isdir(tiff_folder):
        return matches
    for dirpath, _, files in os.walk(tiff_folder):
        for f in files:
            if f.lower().endswith((".tif", ".tiff")) and "corrected" in f.lower():
                matches.append(os.path.join(dirpath, f))
    return matches


def find_all_tifs(tiff_folder):
    matches = []
    if not os.path.isdir(tiff_folder):
        return matches
    for dirpath, _, files in os.walk(tiff_folder):
        for f in files:
            if f.lower().endswith((".tif", ".tiff")):
                matches.append(os.path.join(dirpath, f))
    return matches


def collect_export_manifest(selected_cores, selected_section_numbers,
                             export_xray, export_ct_ortho, export_slices,
                             xray_corrected_only=True,
                             ct_ortho_corrected_only=False,
                             export_xmls=False):
    manifest = {
        "xray_files":             [],
        "ct_ortho_files":         [],
        "slices_dirs":            [],
        "slices_manifest_log":    [],
        "slices_file_count":      0,
        "slices_size_bytes":      0,
        "missing_folders":        [],
        "missing_tifs":           [],
        "renamed_count":          0,
        "total_size_bytes":       0,
        "xml_files":              [],
    }

    def make_dst_filename(src_path, core, section):
        basename = os.path.basename(src_path)
        if basename.upper().startswith(core.upper()):
            return basename
        manifest["renamed_count"] += 1
        grandparent = os.path.basename(
            os.path.dirname(os.path.dirname(src_path)))
        return f"{core}_{section}_{grandparent}_{basename}"

    def resolve_tif_for_export(row, image_list, fallback_finder,
                                corrected_only=False):
        folder       = get_full_path(row["tiff_folder"])
        core         = row["core_name"]
        section      = str(row["section_number"])
        xml_path     = row.get("xml_path", "")
        tif_filename = row.get("tif_filename")

        if not tif_filename and xml_path:
            tif_filename = os.path.splitext(
                os.path.basename(xml_path))[0] + ".tif"

        if tif_filename:
            if corrected_only and "corrected" not in tif_filename.lower():
                return
            tif_path = os.path.join(folder, tif_filename)
            if os.path.exists(tif_path):
                dst_filename = make_dst_filename(tif_path, core, section)
                image_list.append((tif_path, dst_filename, core, section))
                try:
                    manifest["total_size_bytes"] += os.path.getsize(tif_path)
                except OSError:
                    pass
            else:
                manifest["missing_tifs"].append(
                    f"{core} Section {section}: {tif_path}")
        else:
            if os.path.isdir(folder):
                for f in fallback_finder(folder):
                    if (corrected_only
                            and "corrected" not in os.path.basename(f).lower()):
                        continue
                    dst_filename = make_dst_filename(f, core, section)
                    image_list.append((f, dst_filename, core, section))
                    try:
                        manifest["total_size_bytes"] += os.path.getsize(f)
                    except OSError:
                        pass
            else:
                manifest["missing_tifs"].append(
                    f"{core} Section {section}: folder not found: {folder}")

    # XML dedup by absolute source path (shared across all types)
    seen_xml_paths: set = set()

    def _add_xml(row: dict, dst_rel_dir: str,
                 corrected_only: bool = False) -> None:
        """Append the XML paired with this row to the manifest.
        dst_rel_dir is the destination sub-directory relative to export_dir
        (e.g. 'xray_images', 'ct_orthogonal', 'tiff_stacks/…') so the XML
        lands in the same folder as its paired TIF or slice stack."""
        if not export_xmls or not row.get("xml_path"):
            return
        tif_filename = row.get("tif_filename") or ""
        if not tif_filename and row.get("xml_path"):
            tif_filename = (
                os.path.splitext(os.path.basename(row["xml_path"]))[0]
                + ".tif")
        if corrected_only and "corrected" not in tif_filename.lower():
            return
        src_xml = get_full_path(row["xml_path"])
        if src_xml not in seen_xml_paths and os.path.exists(src_xml):
            # Mirror the TIF rename convention so XML and TIF filenames
            # always match.  index.xml is never renamed — its path already
            # encodes core/section context.
            xml_basename = os.path.basename(src_xml)
            core         = row["core_name"]
            section      = str(row["section_number"])
            if (xml_basename.lower() == "index.xml"
                    or xml_basename.upper().startswith(core.upper())):
                dst_xml_filename = xml_basename
            else:
                grandparent = os.path.basename(
                    os.path.dirname(os.path.dirname(src_xml)))
                dst_xml_filename = (
                    f"{core}_{section}_{grandparent}_{xml_basename}")
            manifest["xml_files"].append((src_xml, dst_rel_dir,
                                          dst_xml_filename))
            seen_xml_paths.add(src_xml)

    # ── XRay / CT Ortho ──────────────────────────────────────────────────
    if export_xray:
        for row in get_tiff_folders_for_export(
                selected_cores, selected_section_numbers, "giXRayImage"):
            resolve_tif_for_export(row, manifest["xray_files"],
                                   find_all_tifs,
                                   corrected_only=xray_corrected_only)
            _add_xml(row, dst_rel_dir="xray_images",
                     corrected_only=xray_corrected_only)

    if export_ct_ortho:
        for row in get_tiff_folders_for_export(
                selected_cores, selected_section_numbers, "giCTOrthogonalView"):
            resolve_tif_for_export(row, manifest["ct_ortho_files"],
                                   find_all_tifs,
                                   corrected_only=ct_ortho_corrected_only)
            _add_xml(row, dst_rel_dir="ct_orthogonal",
                     corrected_only=ct_ortho_corrected_only)

    # ── Slices ────────────────────────────────────────────────────────────
    if export_slices:
        dst_basename_counter = {}

        for row in get_all_tiff_folders_for_sections(
                selected_cores, selected_section_numbers):
            if not is_recon_stack(row):
                continue

            folder  = get_full_path(row["tiff_folder"])
            core    = row["core_name"]
            section = str(row["section_number"])
            db_id   = row["id"]

            folder_basename = os.path.basename(folder.rstrip("/"))
            collision_key   = (core, section, folder_basename)

            if collision_key not in dst_basename_counter:
                dst_basename_counter[collision_key] = 1
                dst_folder_name = folder_basename
            else:
                dst_basename_counter[collision_key] += 1
                dst_folder_name = (
                    f"{folder_basename}_"
                    f"{dst_basename_counter[collision_key]}")

            dst_subpath = os.path.join(
                "tiff_stacks", core,
                f"Section_{section}", dst_folder_name)

            # XML goes in the same folder as the slice stack
            _add_xml(row, dst_rel_dir=dst_subpath)

            if not os.path.isdir(folder):
                if folder not in manifest["missing_folders"]:
                    manifest["missing_folders"].append(folder)
                continue

            manifest["slices_dirs"].append(
                (folder, dst_subpath, db_id, core))
            manifest["slices_manifest_log"].append(
                f"  {dst_subpath:<70} db_id={db_id}  src={folder}")

            for f in os.listdir(folder):
                full_f = os.path.join(folder, f)
                if os.path.isfile(full_f):
                    manifest["slices_file_count"] += 1
                    try:
                        manifest["total_size_bytes"] += os.path.getsize(
                            full_f)
                    except OSError:
                        pass

    return manifest


def format_size(n_bytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} PB"


def render_export_preview(manifest):
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("XRay TIFs",          len(manifest["xray_files"]))
    with col2:
        st.metric("CT Orthogonal TIFs", len(manifest["ct_ortho_files"]))
    with col3:
        st.metric("Slices Directories", len(manifest["slices_dirs"]))
    with col4:
        st.metric("XML Files",          len(manifest.get("xml_files", [])))
    with col5:
        st.metric("Total Files",
                  len(manifest["xray_files"])
                  + len(manifest["ct_ortho_files"])
                  + manifest["slices_file_count"]
                  + len(manifest.get("xml_files", [])))
    with col6:
        st.metric("Total Size",
                  format_size(manifest.get("total_size_bytes", 0)))

    if manifest.get("renamed_count", 0) > 0:
        st.info(
            f"✏️ {manifest['renamed_count']} CT Orthogonal file(s) "
            f"will be renamed on export.")

    if manifest["missing_folders"]:
        with st.expander(
                f"⚠️ {len(manifest['missing_folders'])} "
                f"tiff_folder(s) not found on disk"):
            for p in manifest["missing_folders"]:
                st.text(p)

    if manifest["xray_files"]:
        with st.expander(
                f"🖼️ XRay TIFs ({len(manifest['xray_files'])} files)"):
            st.dataframe(
                pd.DataFrame(manifest["xray_files"],
                             columns=["Source Path", "Destination Filename",
                                      "Core", "Section"]),
                use_container_width=True)

    if manifest["ct_ortho_files"]:
        renamed = [(s, d, c, sec) for s, d, c, sec in manifest["ct_ortho_files"]
                   if os.path.basename(s) != d]
        label = (
            f"🔬 CT Orthogonal TIFs ({len(manifest['ct_ortho_files'])} files"
            + (f", {len(renamed)} renamed" if renamed else "") + ")")
        with st.expander(label):
            st.dataframe(
                pd.DataFrame(manifest["ct_ortho_files"],
                             columns=["Source Path", "Destination Filename",
                                      "Core", "Section"]),
                use_container_width=True)

    if manifest["slices_dirs"]:
        with st.expander(
                f"📂 Slices Directories ({len(manifest['slices_dirs'])} dirs, "
                f"{manifest['slices_file_count']:,} files)",
                expanded=True):
            st.caption(
                "Uncheck any directories you want to exclude from the export.")
            select_all = st.checkbox("Select all", value=True,
                                     key="slices_select_all")
            selected_indices = []
            for i, (folder, dst_subpath, db_id, core) in enumerate(
                    manifest["slices_dirs"]):
                checked = st.checkbox(
                    f"`{dst_subpath}`",
                    value=select_all,
                    key=f"slice_dir_{db_id}",
                    help=f"Source: {folder}")
                if checked:
                    selected_indices.append(i)
            manifest["slices_dirs_selected"] = [
                manifest["slices_dirs"][i] for i in selected_indices]
            manifest["slices_manifest_log_selected"] = [
                manifest["slices_manifest_log"][i]
                for i in selected_indices]

    # XML files expander
    if manifest.get("xml_files"):
        renamed_xml_count = sum(
            1 for src_abs, _, dst_fn in manifest["xml_files"]
            if os.path.basename(src_abs) != dst_fn
        )
        label = (
            f"📄 XML Files ({len(manifest['xml_files'])} files"
            + (f", {renamed_xml_count} renamed" if renamed_xml_count else "")
            + ")")
        with st.expander(label):
            st.dataframe(
                pd.DataFrame(
                    [(s, d, f) for s, d, f in manifest["xml_files"]],
                    columns=["Source Path", "Export Directory",
                             "Destination Filename"]),
                use_container_width=True)

    if manifest.get("missing_tifs"):
        with st.expander(
                f"⚠️ {len(manifest['missing_tifs'])} "
                f"TIF file(s) expected but not found on disk"):
            st.warning(
                "These files are in the database but the TIF was not "
                "found at the expected path.")
            for p in manifest["missing_tifs"]:
                st.text(p)


def generate_rsync_script(manifest, export_dir):
    xray_dst     = os.path.join(export_dir, "xray_images")
    ct_ortho_dst = os.path.join(export_dir, "ct_orthogonal")
    log_file     = os.path.join(export_dir, "export_log.txt")

    lines = [
        "#!/bin/bash",
        "# ============================================================",
        "#  CT Data Export Script — generated by CT Data Manager",
        f"#  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"#  Destination root: {export_dir}",
        "#",
        "#  Re-running this script is safe — rsync skips files that",
        "#  already exist at the destination (--ignore-existing).",
        "# ============================================================",
        "",
        f'mkdir -p "{export_dir}"',
        f'LOG="{log_file}"',
        'echo "Export started: $(date)" >> "$LOG"',
        "",
    ]

    def emit_file_copies(file_list, dst_dir, section_label):
        if not file_list:
            return
        lines.append(f"# --- {section_label} ---")
        lines.append(f'mkdir -p "{dst_dir}"')

        same_name = [(s, d, c, sec) for s, d, c, sec in file_list
                     if os.path.basename(s) == d]
        renamed   = [(s, d, c, sec) for s, d, c, sec in file_list
                     if os.path.basename(s) != d]

        by_folder = {}
        for src, dst_fn, core, section in same_name:
            by_folder.setdefault(
                os.path.dirname(src), []).append(os.path.basename(src))
        for folder, filenames in by_folder.items():
            includes = " ".join(f'--include="{f}"' for f in filenames)
            lines.append(
                f'rsync -av --ignore-existing {includes} --exclude="*" '
                f'"{folder}/" "{dst_dir}/" >> "$LOG" 2>&1')

        if renamed:
            lines.append("# -- renamed files --")
            for src, dst_fn, core, section in renamed:
                dst_path = os.path.join(dst_dir, dst_fn)
                lines.append(
                    f'[ ! -f "{dst_path}" ] && cp "{src}" "{dst_path}" '
                    f'&& echo "Copied: {dst_fn}" >> "$LOG"')
        lines.append("")

    emit_file_copies(manifest["xray_files"],     xray_dst,     "XRay Images")
    emit_file_copies(manifest["ct_ortho_files"], ct_ortho_dst, "CT Orthogonal Views")

    # ── Slices ────────────────────────────────────────────────────────────
    if manifest["slices_dirs"]:
        active_dirs = manifest.get("slices_dirs_selected",
                                   manifest["slices_dirs"])
        active_log  = manifest.get("slices_manifest_log_selected",
                                   manifest["slices_manifest_log"])
        if active_dirs:
            lines.append("# --- Slices Directories ---")
            lines.append(
                "# Destination: tiff_stacks/{core}/Section_{section}/"
                "{folder_basename}")
            lines.append("")
            lines.append("# -- Slices manifest --")
            lines.append('echo "=== SLICES EXPORT MANIFEST ===" >> "$LOG"')
            lines.append(
                f'echo "  {"Destination":<70} DB ID   Source" >> "$LOG"')
            for log_line in active_log:
                escaped = log_line.replace('"', '\\"')
                lines.append(f'echo "{escaped}" >> "$LOG"')
            lines.append('echo "==============================" >> "$LOG"')
            lines.append("")
            for folder, dst_subpath, db_id, core in active_dirs:
                dst_path = os.path.join(export_dir, dst_subpath)
                lines.append(f'mkdir -p "{dst_path}"')
                lines.append(
                    f'rsync -av --exclude="*/" --ignore-existing '
                    f'"{folder}/" "{dst_path}/" >> "$LOG" 2>&1')
            lines.append("")

    # ── XMLs (alongside paired TIFs/slice folders) ──────────────────────
    if manifest.get("xml_files"):
        lines.append("# --- XML Files (alongside paired TIFs) ---")
        same_name_by_dir: dict = {}
        renamed_xmls = []
        for src_abs, dst_rel_dir, dst_xml_filename in manifest["xml_files"]:
            src_dir  = os.path.dirname(src_abs)
            dst_dir  = os.path.join(export_dir, dst_rel_dir)
            src_name = os.path.basename(src_abs)
            if src_name == dst_xml_filename:
                same_name_by_dir.setdefault(
                    (src_dir, dst_dir), []).append(src_name)
            else:
                renamed_xmls.append((src_abs, dst_dir, dst_xml_filename))

        for (src_dir, dst_dir), filenames in same_name_by_dir.items():
            lines.append(f'mkdir -p "{dst_dir}"')
            includes = " ".join(f'--include="{f}"' for f in filenames)
            lines.append(
                f'rsync -av --ignore-existing {includes} --exclude="*" '
                f'"{src_dir}/" "{dst_dir}/" >> "$LOG" 2>&1')

        if renamed_xmls:
            lines.append("# -- renamed XML files --")
            for src_abs, dst_dir, dst_xml_filename in renamed_xmls:
                dst_path = os.path.join(dst_dir, dst_xml_filename)
                lines.append(
                    f'mkdir -p "{dst_dir}"')
                lines.append(
                    f'[ ! -f "{dst_path}" ] && cp "{src_abs}" "{dst_path}" '
                    f'&& echo "Copied: {dst_xml_filename}" >> "$LOG"')
        lines.append("")

    lines += [
        'echo "Export complete: $(date)" >> "$LOG"',
        'echo ""',
        'echo "Export complete. See $LOG for details."',
    ]

    return "\n".join(lines)


# === Streamlit App ===
def main():
    st.set_page_config(page_title="CT Data Manager", layout="wide")
    st.title("🔬 CT Scan Data Manager")

    with st.sidebar:
        st.header("⚙️ Settings")
        ct_root = st.text_input(
            "CT Root Folder",
            value=get_full_path("CT_Data"),
            help="Path to CT data directory"
        )

    tab1, tab2, tab3, tab4 = st.tabs(
        ["1️⃣ Import Scans", "2️⃣ Database View", "3️⃣ Path Maintenance", "4️⃣ Export Data"]
    )

    # === TAB 1: Import Scans ===
    with tab1:
        st.header("Import CT Scans")
        st.write("""
        **Workflow:**
        1. Scan directory for new XML files
        2. Validate Core-ID and Section-ID against database
        3. Import valid records — invalid records are skipped automatically
        4. Optionally fix any mismatches and re-scan to import them
        """)

        if st.button("🔍 Scan Directory", use_container_width=True, type="primary"):
            with st.spinner("Scanning and validating..."):
                records = scan_ct_folders(ct_root)
                validated = validate_against_database(records)
                st.session_state.validated_records = validated

        if "validated_records" in st.session_state:
            validated = st.session_state.validated_records
            summary_df, summary_data = get_validation_summary(validated)

            if not summary_df.empty:
                total = len(summary_df)
                valid = len(summary_df[summary_df["Status"] == "✅ Valid"])
                invalid = len(summary_df[summary_df["Status"] == "❌ Invalid"])

                col1, col2, col3 = st.columns(3)
                with col1: st.metric("Found", total)
                with col2: st.metric("Valid", valid)
                with col3: st.metric("Needs Fixing", invalid)

                st.dataframe(summary_df, use_container_width=True)

                if invalid > 0:
                    st.markdown("---")
                    st.subheader("🔧 Fix Invalid Records")
                    st.warning(f"⚠️ {invalid} core/section combination(s) could not be matched in the database and will be skipped on import")

                    invalid_df = summary_df[summary_df["Status"] == "❌ Invalid"]
                    edit_data = {}

                    for idx, row in invalid_df.iterrows():
                        core = row["Core"]
                        section = row["Section"]
                        issues = row["Issues"]
                        xml_count = row["XML Count"]

                        with st.expander(f"🔧 {core} - Section {section} ({xml_count} XMLs) - {issues}"):
                            col1, col2 = st.columns(2)
                            with col1:
                                new_core = st.text_input("New Core-ID", key=f"fix_core_{core}_{section}", placeholder=core)
                            with col2:
                                new_section = st.text_input("New Section-ID", key=f"fix_section_{core}_{section}", placeholder=str(section))
                            if new_core or new_section:
                                edit_data[(core, section)] = {"new_core": new_core, "new_section": new_section}

                    if edit_data:
                        st.markdown("---")
                        if st.button("💾 Apply Fixes to Invalid XMLs", use_container_width=True, type="primary", key="fix_invalid_btn"):
                            fm = CTFileManager(ct_root)
                            total_files = sum(len(summary_data[(core, section)]["records"]) for (core, section) in edit_data.keys())
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            total_updated = 0
                            total_failed = 0
                            current_file = 0

                            for (core, section), changes in edit_data.items():
                                key = (core, section)
                                if key in summary_data:
                                    for val in summary_data[key]["records"]:
                                        current_file += 1
                                        record = val["record"]
                                        xml_path = record["xml_path"]
                                        status_text.text(f"Processing {current_file}/{total_files}: {os.path.basename(xml_path)}")
                                        success = True
                                        if changes["new_core"]:
                                            if not fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"]):
                                                success = False
                                        if changes["new_section"] and success:
                                            section_id_ok = fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"])
                                            section_num_ok = fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                            if not section_id_ok and not section_num_ok:
                                                success = False
                                        if success:
                                            total_updated += 1
                                        else:
                                            total_failed += 1
                                        progress_bar.progress(current_file / total_files)

                            progress_bar.empty()
                            status_text.empty()
                            if total_failed > 0:
                                st.warning(f"⚠️ Updated {total_updated} XML files, {total_failed} failed")
                            else:
                                st.success(f"✅ Successfully updated {total_updated} XML files")
                            time.sleep(1.5)
                            if "validated_records" in st.session_state:
                                del st.session_state.validated_records
                            st.info("🔄 Re-scanning to verify fixes...")
                            time.sleep(0.5)
                            records = scan_ct_folders(ct_root)
                            validated = validate_against_database(records)
                            st.session_state.validated_records = validated
                            st.rerun()

                if valid > 0:
                    st.markdown("---")
                    st.subheader("✏️ Edit Valid Records (Optional)")
                    st.info("These records passed validation but you can still edit them if needed")

                    valid_df = summary_df[summary_df["Status"] == "✅ Valid"]
                    valid_edit_data = {}

                    for idx, row in valid_df.iterrows():
                        core = row["Core"]
                        section = row["Section"]
                        xml_count = row["XML Count"]

                        with st.expander(f"✏️ {core} - Section {section} ({xml_count} XMLs)"):
                            col1, col2 = st.columns(2)
                            with col1:
                                new_core = st.text_input("New Core-ID", key=f"edit_core_{core}_{section}", placeholder=core)
                            with col2:
                                new_section = st.text_input("New Section-ID", key=f"edit_section_{core}_{section}", placeholder=str(section))
                            if new_core or new_section:
                                valid_edit_data[(core, section)] = {"new_core": new_core, "new_section": new_section}

                    if valid_edit_data:
                        st.markdown("---")
                        if st.button("💾 Apply Edits to Valid XMLs", use_container_width=True, type="secondary", key="edit_valid_btn"):
                            validation_failed = False
                            validation_errors = []

                            with get_connection() as conn:
                                for (core, section), changes in valid_edit_data.items():
                                    if changes["new_core"]:
                                        core_exists = conn.execute(
                                            text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                                            {"core_name": changes["new_core"].strip()}
                                        ).fetchone()
                                        if not core_exists:
                                            validation_failed = True
                                            validation_errors.append(f"Core '{changes['new_core']}' does not exist in database")

                                    if changes["new_section"]:
                                        check_core = changes["new_core"] if changes["new_core"] else core
                                        core_row = conn.execute(
                                            text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                                            {"core_name": check_core.strip()}
                                        ).fetchone()
                                        if core_row:
                                            try:
                                                new_section_int = int(changes["new_section"])
                                                section_exists = conn.execute(
                                                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                                                    {"core_id": core_row[0], "section_number": new_section_int}
                                                ).fetchone()
                                                if not section_exists:
                                                    validation_failed = True
                                                    validation_errors.append(f"Section {changes['new_section']} does not exist for core '{check_core}'")
                                            except (TypeError, ValueError):
                                                validation_failed = True
                                                validation_errors.append(f"Invalid section number format: '{changes['new_section']}'")

                            if validation_failed:
                                st.error("❌ Cannot apply edits - new names are invalid:")
                                for error in validation_errors:
                                    st.error(f"  • {error}")
                            else:
                                fm = CTFileManager(ct_root)

                                # Only edit XMLs not already in the database
                                with get_connection() as conn:
                                    existing_paths = set(
                                        row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml"))
                                    )

                                filtered_records = {}
                                skipped_already_imported = 0
                                for (core, section) in valid_edit_data.keys():
                                    key = (core, section)
                                    if key in summary_data:
                                        unimported = [v for v in summary_data[key]["records"]
                                                      if v["record"]["xml_path"] not in existing_paths]
                                        filtered_records[key] = unimported
                                        skipped_already_imported += len(summary_data[key]["records"]) - len(unimported)

                                if skipped_already_imported > 0:
                                    st.info(f"ℹ️ Skipping {skipped_already_imported} XML(s) already in database (edits not needed)")

                                total_files = sum(len(recs) for recs in filtered_records.values())

                                if total_files == 0:
                                    st.warning("⚠️ All XMLs for the selected sections are already in the database. Nothing to edit.")
                                else:
                                    progress_bar = st.progress(0)
                                    status_text = st.empty()
                                    total_updated = 0
                                    total_failed = 0
                                    current_file = 0

                                    for (core, section), changes in valid_edit_data.items():
                                        key = (core, section)
                                        if key in filtered_records:
                                            for val in filtered_records[key]:
                                                current_file += 1
                                                record = val["record"]
                                                xml_path = record["xml_path"]
                                                status_text.text(f"Processing {current_file}/{total_files}: {os.path.basename(xml_path)}")
                                                success = True
                                                if changes["new_core"]:
                                                    if not fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"]):
                                                        success = False
                                                if changes["new_section"] and success:
                                                    section_id_ok = fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"])
                                                    section_num_ok = fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                                    if not section_id_ok and not section_num_ok:
                                                        success = False
                                                if success:
                                                    total_updated += 1
                                                else:
                                                    total_failed += 1
                                                progress_bar.progress(current_file / total_files)

                                    progress_bar.empty()
                                    status_text.empty()
                                    if total_failed > 0:
                                        st.warning(f"⚠️ Updated {total_updated} XML files, {total_failed} failed")
                                    else:
                                        st.success(f"✅ Successfully updated {total_updated} XML files")

                                time.sleep(1.5)
                                if "validated_records" in st.session_state:
                                    del st.session_state.validated_records
                                st.info("🔄 Re-scanning to verify edits...")
                                time.sleep(0.5)
                                records = scan_ct_folders(ct_root)
                                validated = validate_against_database(records)
                                st.session_state.validated_records = validated
                                st.rerun()

                if valid > 0:
                    st.markdown("---")
                    if invalid == 0:
                        st.success("✅ All records validated! Ready to import.")
                    else:
                        st.warning(f"⚠️ {invalid} invalid record(s) will be skipped. {valid} valid record(s) are ready to import.")

                    if st.button("📥 Import Valid Records to Database", use_container_width=True, type="primary"):
                        with st.spinner("Importing to database..."):
                            saved, skipped_path, skipped_fp, failed = import_to_database(validated)
                        invalid_skipped = sum(1 for v in validated if v["status"] != "valid")
                        actual_errors = failed - invalid_skipped
                        if saved > 0:
                            st.success(f"✅ Imported {saved} new XML files to database")
                        if skipped_path > 0:
                            st.info(f"ℹ️ Skipped {skipped_path} files (already in database at same path)")
                        if skipped_fp > 0:
                            st.warning(f"⚠️ Skipped {skipped_fp} files (same scan exists at different path — use Tab 3)")
                        if invalid_skipped > 0:
                            st.info(f"ℹ️ Skipped {invalid_skipped} invalid record(s) — fix them above and re-scan to import")
                        if actual_errors > 0:
                            st.error(f"❌ {actual_errors} record(s) failed to import (check console for details)")
                        if "validated_records" in st.session_state:
                            del st.session_state.validated_records
                        time.sleep(2)
                        st.rerun()
            else:
                st.warning("⚠️ No valid records found after validation")
        else:
            st.info("👆 Click 'Scan Directory' to begin")

    # === TAB 2: Database View ===
    with tab2:
        st.header("Database View")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

        ct_xml_df = get_ct_xml_summary()

        if not ct_xml_df.empty:
            st.subheader("📊 CT Scans in Database")
            st.dataframe(ct_xml_df, use_container_width=True)
            st.info(f"Total: {len(ct_xml_df)} core/section combinations in database")
            st.download_button(
                label="📥 Download CSV",
                data=ct_xml_df.to_csv(index=False),
                file_name="ct_xml_summary.csv",
                mime="text/csv",
                use_container_width=True
            )
            with st.expander("📋 View Detailed Records"):
                with get_connection() as conn:
                    result = conn.execute(text("""
                        SELECT core_name, section_number, xml_root_tag,
                               scan_id, image_type, processing_stage, xml_path
                        FROM ct_xml
                        ORDER BY core_name, section_number, xml_root_tag, image_type
                    """))
                    detailed = [dict(row._mapping) for row in result.fetchall()]
                if detailed:
                    detail_df = pd.DataFrame(detailed)
                    detail_df.columns = ["Core", "Section", "Root Tag", "Scan ID", "Image Type", "Processing Stage", "XML Path"]
                    st.dataframe(detail_df, use_container_width=True)
        else:
            st.info("No records in ct_xml table yet. Import scans from Tab 1 first.")

    # === TAB 3: Path Maintenance ===
    with tab3:
        st.header("Path Maintenance")
        st.write("""
        **Use this after reorganizing files or moving between hard drives:**
        1. Check which database records point to missing files
        2. Search filesystem to find where files moved to
        3. Update database with new paths
        """)

        if st.button("🔍 Check for Missing Files", use_container_width=True, type="primary"):
            with st.spinner("Verifying paths..."):
                verification = verify_xml_paths(ct_root)
                st.session_state.path_verification = verification

        if "path_verification" in st.session_state and st.session_state.path_verification is not None:
            verify = st.session_state.path_verification
            col1, col2, col3 = st.columns(3)
            with col1: st.metric("Total Records", verify["total"])
            with col2: st.metric("✅ Found", len(verify["exists"]))
            with col3: st.metric("❌ Missing", len(verify["missing"]))

            if verify["missing"]:
                st.markdown("---")
                st.warning(f"⚠️ {len(verify['missing'])} XML files not found at recorded paths")
                with st.expander("📋 View Missing Files"):
                    missing_df = pd.DataFrame(verify["missing"])
                    if not missing_df.empty:
                        st.dataframe(missing_df[["core_name", "section_number", "xml_root_tag", "image_type", "xml_path"]], use_container_width=True)

                st.markdown("---")
                st.subheader("🔍 Search for Moved Files")
                if st.button("🔎 Search for Moved Files", use_container_width=True, type="primary"):
                    with st.spinner(f"Searching {ct_root} for {len(verify['missing'])} missing files..."):
                        search_results = find_moved_files(ct_root, verify["missing"])
                        st.session_state.path_search_results = search_results

                if "path_search_results" in st.session_state and st.session_state.path_search_results is not None:
                    results = st.session_state.path_search_results
                    col1, col2 = st.columns(2)
                    with col1: st.metric("✅ Found", len(results["matches"]))
                    with col2: st.metric("❌ Not Found", len(results["not_found"]))

                    if results["matches"]:
                        st.success(f"🎉 Found {len(results['matches'])} moved files!")
                        with st.expander("📋 View Path Changes", expanded=True):
                            for match in results["matches"][:10]:
                                st.write(f"**{match['core_name']} - Section {match['section_number']} - {match['xml_root_tag']}**")
                                st.text(f"  Old: {match['old_xml_path']}")
                                st.text(f"  New: {match['new_xml_path']}")
                            if len(results["matches"]) > 10:
                                st.info(f"... and {len(results['matches']) - 10} more")
                        st.markdown("---")
                        if st.button("💾 Update Database Paths", use_container_width=True, type="primary"):
                            with st.spinner("Updating paths..."):
                                updated, skipped = update_xml_paths(results["matches"])
                            if skipped > 0:
                                st.warning(f"⚠️ Updated {updated} records, skipped {skipped} (see console for conflicts)")
                            else:
                                st.success(f"✅ Updated {updated} records in database")
                            if "path_verification" in st.session_state:
                                del st.session_state.path_verification
                            if "path_search_results" in st.session_state:
                                del st.session_state.path_search_results
                            st.rerun()

                    if results["not_found"]:
                        st.error(f"❌ Could not find {len(results['not_found'])} files")
                        with st.expander("📋 View Files Not Found"):
                            not_found_df = pd.DataFrame(results["not_found"])
                            if not not_found_df.empty:
                                st.dataframe(not_found_df[["core_name", "section_number", "xml_root_tag", "xml_path"]], use_container_width=True)
            else:
                st.success("✅ All XML files found at their recorded paths!")
        else:
            st.info("👆 Click 'Check for Missing Files' to begin")

    # === TAB 4: Export Data ===
    with tab4:
        st.header("Export Data")
        st.write(
            "Select cores and sections, choose what to export, then "
            "download the rsync script.")

        all_cruises = get_cruises_from_db()
        if not all_cruises:
            st.warning("No CT data found in database.")
        else:
            cruise_options = {name: cid for cid, name in all_cruises}
            selected_cruise_names = st.multiselect(
                "Filter by Cruise(s)",
                options=list(cruise_options.keys()),
                help="Select one or more cruises to filter the core list."
            )
            selected_cruise_ids = [cruise_options[n]
                                   for n in selected_cruise_names]

            if selected_cruise_ids:
                available_cores = get_cores_for_cruises(selected_cruise_ids)
            else:
                available_cores = get_cores_from_db()

            if not available_cores:
                st.warning(
                    "No cores with CT data found for the selected cruise(s).")
            else:
                select_all_cores = st.checkbox(
                    f"Select All Cores ({len(available_cores)})",
                    value=False,
                    key="export_select_all_cores")
                if select_all_cores:
                    selected_cores = available_cores
                    st.info(
                        f"✅ All {len(available_cores)} cores selected"
                        + (f" from {', '.join(selected_cruise_names)}"
                           if selected_cruise_names else ""))
                else:
                    selected_cores = st.multiselect(
                        "Select Core(s)", options=available_cores)

            if (not selected_cruise_ids and not select_all_cores
                    and not selected_cores):
                st.info(
                    "👆 Select at least one cruise or core to see "
                    "available sections.")
            elif not available_cores:
                pass
            elif not selected_cores:
                st.info(
                    "👆 Select at least one core to see available sections.")
            else:
                st.markdown("---")
                st.subheader("Select Sections")
                core_section_pairs = get_sections_for_cores(selected_cores)

                if not core_section_pairs:
                    st.warning(
                        "No CT data found in the database for the "
                        "selected cores.")
                else:
                    sections_by_core = {}
                    for core, sec in core_section_pairs:
                        sections_by_core.setdefault(core, []).append(sec)

                    selected_section_keys = []
                    for core in selected_cores:
                        sections = sections_by_core.get(core, [])
                        if not sections:
                            continue
                        with st.expander(
                                f"📦 {core} — {len(sections)} section(s)",
                                expanded=False):
                            select_all_secs = st.checkbox(
                                "Select all sections", value=True,
                                key=f"all_secs_{core}")
                            if select_all_secs:
                                chosen_secs = sections
                                st.caption(
                                    f"All {len(sections)} sections selected: "
                                    f"{', '.join(str(s) for s in sections)}")
                            else:
                                chosen_secs = []
                                cols_per_row = 6
                                sec_chunks = [
                                    sections[i:i + cols_per_row]
                                    for i in range(0, len(sections),
                                                   cols_per_row)]
                                for chunk in sec_chunks:
                                    cols = st.columns(len(chunk))
                                    for col, sec in zip(cols, chunk):
                                        with col:
                                            if st.checkbox(
                                                    str(sec), value=True,
                                                    key=f"sec_{core}_{sec}"):
                                                chosen_secs.append(sec)
                            for sec in chosen_secs:
                                selected_section_keys.append((core, sec))

                    selected_cores_final = list(
                        {core for core, _ in selected_section_keys})
                    selected_section_numbers = list(
                        {sec for _, sec in selected_section_keys})

                    if not selected_section_keys:
                        st.info("Select at least one section to continue.")
                    else:
                        st.caption(
                            f"**{len(selected_section_keys)} core/section "
                            f"combinations selected**")
                        st.markdown("---")
                        st.subheader("What to Export")

                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            export_xray = st.checkbox(
                                "🖼️ XRay Images", value=True)
                            if export_xray:
                                xray_corrected_only = (
                                    st.radio(
                                        "Include",
                                        ["Corrected only", "All images"],
                                        index=0,
                                        key="xray_filter",
                                        horizontal=True)
                                    == "Corrected only")
                            else:
                                xray_corrected_only = True
                        with col2:
                            export_ct_ortho = st.checkbox(
                                "🔬 CT Orthogonal Views", value=True)
                            if export_ct_ortho:
                                ct_ortho_corrected_only = (
                                    st.radio(
                                        "Include",
                                        ["All images", "Corrected only"],
                                        index=0,
                                        key="ct_ortho_filter",
                                        horizontal=True)
                                    == "Corrected only")
                            else:
                                ct_ortho_corrected_only = False
                        with col3:
                            export_slices = st.checkbox(
                                "📂 Slices Directories", value=True)
                        with col4:
                            export_xmls = st.checkbox(
                                "📄 Export XMLs", value=True,
                                help=(
                                    "Copy XML metadata files alongside their "
                                    "TIFs (mirrored folder structure). "
                                    "Required for pixel-per-cm resolution in "
                                    "the Core Correlator."))

                        st.markdown("---")
                        export_dir = st.text_input(
                            "Export Directory",
                            value=get_full_path("CT_Export"))

                        st.markdown("---")
                        if st.button("🔍 Preview Export",
                                     use_container_width=True):
                            if not any([export_xray, export_ct_ortho,
                                        export_slices, export_xmls]):
                                st.warning(
                                    "Select at least one export type.")
                            else:
                                with st.spinner(
                                        "Scanning for files to export..."):
                                    preview = collect_export_manifest(
                                        selected_cores_final,
                                        selected_section_numbers,
                                        export_xray,
                                        export_ct_ortho,
                                        export_slices,
                                        xray_corrected_only=xray_corrected_only,
                                        ct_ortho_corrected_only=ct_ortho_corrected_only,
                                        export_xmls=export_xmls,
                                    )
                                st.session_state.export_preview = preview
                                st.session_state.export_dir = export_dir
                                st.session_state.export_cores_final = (
                                    selected_cores_final)
                                st.session_state.export_section_numbers = (
                                    selected_section_numbers)
                        if "export_preview" in st.session_state:
                            preview = st.session_state.export_preview
                            render_export_preview(preview)

                            total_files = (
                                len(preview.get("xray_files", []))
                                + len(preview.get("ct_ortho_files", []))
                                + preview.get("slices_file_count", 0)
                                + len(preview.get("xml_files", []))
                            )

                            if total_files == 0:
                                st.warning(
                                    "⚠️ No files matched the selection. "
                                    "Nothing to export.")
                            else:
                                st.markdown("---")
                                st.info(
                                    "📋 Download the **rsync script** to copy "
                                    "files on the server.")

                                script_content = generate_rsync_script(
                                    preview, st.session_state.export_dir)

                                st.download_button(
                                    label=(
                                        f"📥 Download Export Script "
                                        f"({total_files:,} files)"),
                                    data=script_content,
                                    file_name="ct_export.sh",
                                    mime="text/plain",
                                    use_container_width=True,
                                    type="primary")

                                st.write(
                                    "**To run:** `bash ct_export.sh`")
                                st.write("**Output structure:**")
                                st.code(
                                    f"{st.session_state.export_dir}/\n"
                                    f"├── xray_images/\n"
                                    f"├── ct_orthogonal/\n"
                                    f"├── tiff_stacks/\n"
                                    f"│   └── {{core}}/\n"
                                    f"│       └── Section_{{n}}/\n"
                                    f"│           └── Slices/\n"
                                    f"└── (XML files alongside paired images)",
                                    language="text")
                                with st.expander(
                                        "👀 Preview script contents"):
                                    st.code(script_content, language="bash")


if __name__ == "__main__":
    main()
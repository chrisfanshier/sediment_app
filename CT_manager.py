import os
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import time
import shutil

# === Database Setup ===
engine = create_engine("postgresql+psycopg2://postgres:madmaxfuryroad@localhost:5432/shipside")

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
            return None

        section_id = get_text("Section-ID", "section-id", "sectionID")
        if not section_id:
            section_id = get_text("Section-Number", "section-number")

        core_name = get_text("Core-ID", "coreID")
        if core_name:
            core_name = core_name.strip().replace("_", "-").upper()

        total_scanned_length = get_text("Total-Scanned-Length", "total-scanned-length")

        data = {
            "core_name": core_name,
            "scan_id": get_text("Scan-ID", "scanID"),
            "section_id": section_id,
            "image_type": get_text("Image-Type", "image-type"),
            "processing_stage": get_text("Processing-Stage", "processing-stage"),
            "section_number": section_id,
            "xml_root_tag": root_tag,
            "total_scanned_length": total_scanned_length
        }
        
        # Explicitly help GC by deleting tree reference
        del tree
        
        return data
    except Exception as e:
        print(f"Error parsing {xml_path}: {e}")
        return None

# === File Manager Class ===
class CTFileManager:
    """Handles file operations"""
    
    def __init__(self, ct_root):
        self.ct_root = ct_root
    
    def edit_xml_field(self, xml_path, field_name, new_value):
        """Edit a specific field in an XML file"""
        full_path = xml_path if os.path.isabs(xml_path) else os.path.join(self.ct_root, xml_path)
        
        try:
            if not os.path.exists(full_path):
                print(f"File not found: {full_path}")
                return False
            
            tree = ET.parse(full_path)
            root = tree.getroot()
            
            # Define all possible tag name variants
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
                # Check if element tag matches any variant (case-insensitive)
                if any(elem.tag.lower() == tag.lower() for tag in possible_tags):
                    old_value = elem.text
                    elem.text = new_value
                    found = True
                    updated_tag = elem.tag
                    break
            
            if found:
                # Write to temp file first
                temp_path = full_path + ".tmp"
                tree.write(temp_path, encoding='utf-8', xml_declaration=True)
                
                # Explicitly delete tree to release file handle
                del tree
                
                # Small delay to ensure file handle is released
                time.sleep(0.05)
                
                # Replace original with temp file
                shutil.move(temp_path, full_path)
                
                print(f"Updated {updated_tag}: '{old_value}' → '{new_value}' in {os.path.basename(full_path)}")
                return True
            else:
                del tree
                print(f"Field '{field_name}' (tried variants: {', '.join(possible_tags)}) not found in {os.path.basename(full_path)}")
                return False
            
        except Exception as e:
            print(f"Error editing XML {full_path}: {e}")
            # Clean up temp file if it exists
            temp_path = full_path + ".tmp"
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            return False

# === PHASE 1: Scan & Validate ===
def scan_ct_folders(ct_root):
    """Scan CT folders for XML files"""
    found = []
    for root, dirs, files in os.walk(ct_root):
        xmls = [f for f in files if f.lower().endswith(".xml")]
        for xml_file in xmls:
            xml_path = os.path.join(root, xml_file)
            meta = parse_ct_xml(xml_path)
            if meta and meta["core_name"]:
                record = {
                    **meta,
                    "xml_path": xml_path,
                    "tiff_folder": root,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                found.append(record)
    return found

def validate_against_database(records):
    """Validate each record against database and return validation status"""
    validated_records = []
    
    for record in records:
        validation = {
            "record": record,
            "core_exists": False,
            "section_exists": False,
            "issues": [],
            "status": "unknown"
        }
        
        # Check core
        with engine.connect() as conn:
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
                
                # Check section
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
    """Create summary table grouped by core/section with validation status"""
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
        
        # If any record is invalid, mark the whole group as invalid
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
    """
    Import validated records directly to ct_xml
    Uses fingerprint deduplication to prevent duplicates
    """
    saved_count = 0
    skipped_by_path = 0
    skipped_by_fingerprint = 0
    failed_count = 0
    
    with engine.begin() as conn:
        # Get existing paths
        existing_paths = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml"))
        )
        
        # Get existing fingerprints
        existing_fingerprints = set()
        result = conn.execute(text("""
            SELECT 
                core_name, 
                section_number, 
                xml_root_tag, 
                COALESCE(image_type, '') as image_type, 
                COALESCE(processing_stage, '') as processing_stage
            FROM ct_xml
        """))
        for row in result:
            fingerprint = (
                row[0],  # core_name
                str(row[1]),  # section_number
                row[2],  # xml_root_tag
                row[3],  # image_type
                row[4]   # processing_stage
            )
            existing_fingerprints.add(fingerprint)
        
        for val in validated_records:
            if val["status"] != "valid":
                failed_count += 1
                continue
            
            record = val["record"]
            
            # CHECK 1: Skip if path exists (exact same file location)
            if record["xml_path"] in existing_paths:
                skipped_by_path += 1
                continue
            
            # CHECK 2: Skip if fingerprint exists (same scan, different location)
            fingerprint = (
                record["core_name"],
                str(record["section_number"]),
                record["xml_root_tag"],
                record.get("image_type", "") or "",
                record.get("processing_stage", "") or ""
            )
            
            if fingerprint in existing_fingerprints:
                print(f"⚠️ Skipping duplicate fingerprint (file may have moved): {record['core_name']}-{record['section_number']} {record['xml_root_tag']} {fingerprint[3]}")
                print(f"   Path: {record['xml_path']}")
                skipped_by_fingerprint += 1
                continue
            
            # PASSED BOTH CHECKS - Import this record
            try:
                # Get core_id
                core_row = conn.execute(
                    text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                    {"core_name": record["core_name"].strip()}
                ).fetchone()
                core_id = core_row[0]
                
                # Get section_id
                section_number_int = int(record["section_number"])
                section_row = conn.execute(
                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                    {"core_id": core_id, "section_number": section_number_int}
                ).fetchone()
                section_id = section_row[0]
                
                # Insert to ct_xml
                conn.execute(
                    text("""
                        INSERT INTO ct_xml (
                            core_id, core_name, section_id, scan_id, image_type,
                            processing_stage, section_number,
                            xml_path, tiff_folder, xml_root_tag, timestamp
                        ) VALUES (
                            :core_id, :core_name, :section_id, :scan_id, :image_type,
                            :processing_stage, :section_number,
                            :xml_path, :tiff_folder, :xml_root_tag, :timestamp
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
                        timestamp=record["timestamp"]
                    )
                )
                saved_count += 1
                
            except Exception as e:
                print(f"❌ Error importing {record['xml_path']}: {e}")
                failed_count += 1
    
    # Print detailed report
    if skipped_by_path > 0:
        print(f"ℹ️ Skipped {skipped_by_path} records (path already exists)")
    if skipped_by_fingerprint > 0:
        print(f"ℹ️ Skipped {skipped_by_fingerprint} records (fingerprint already exists - use Tab 3 to update paths)")
    
    return saved_count, skipped_by_path, skipped_by_fingerprint, failed_count

# === PHASE 3: View ct_xml table ===
def get_ct_xml_summary():
    """Get summary of what's in ct_xml with separate columns for CT directories and images"""
    with engine.connect() as conn:
        # Get all records
        result = conn.execute(text("""
            SELECT 
                core_name,
                section_number,
                xml_root_tag,
                image_type,
                processing_stage
            FROM ct_xml
            ORDER BY core_name, section_number
        """))
        rows = [dict(row._mapping) for row in result.fetchall()]
    
    if not rows:
        return pd.DataFrame()
    
    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(rows)
    
    # Directory types (CT scans with processing stages)
    # These come from both geotek-ct-stack and geotek-ct-recon
    directory_types = ["CT-Volume", "Helical", "Laminography"]
    
    # Image types (photos/views without processing stages)
    # These come from geotek-image
    image_types = ["giXRayImage", "giCTOrthogonalView"]
    
    summary_rows = []
    
    # Get unique core/section pairs
    all_pairs = df[["core_name", "section_number"]].drop_duplicates()
    
    for _, row in all_pairs.iterrows():
        core = row["core_name"]
        section = row["section_number"]
        
        subdf = df[(df["core_name"] == core) & (df["section_number"] == section)]
        
        # Count total XMLs
        xml_count = len(subdf)
        
        # Build directories column (CT scans with stages)
        # Filter to only geotek-ct-stack and geotek-ct-recon records
        ct_scan_records = subdf[subdf["xml_root_tag"].isin(["geotek-ct-stack", "geotek-ct-recon"])]
        
        directories = []
        for dtype in directory_types:
            # Get all stages for this image type from CT scan records
            stages = ct_scan_records.loc[
                ct_scan_records["image_type"] == dtype, 
                "processing_stage"
            ].dropna().unique()
            
            if len(stages) > 0:
                stage_list = ", ".join(sorted(stages))
                directories.append(f"{dtype} ({stage_list})")
        
        directories_str = "; ".join(directories) if directories else ""
        
        # Build images column (image types without stages)
        # Filter to only geotek-image records
        image_records = subdf[subdf["xml_root_tag"] == "geotek-image"]
        
        images = []
        for itype in image_types:
            if (image_records["image_type"] == itype).any():
                images.append(itype)
        
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
    """Check which XMLs in database still exist at their recorded paths"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                id,
                core_name,
                section_number,
                xml_root_tag,
                image_type,
                processing_stage,
                xml_path,
                tiff_folder
            FROM ct_xml
            ORDER BY core_name, section_number
        """))
        db_records = [dict(row._mapping) for row in result.fetchall()]
    
    results = {
        "exists": [],
        "missing": [],
        "total": len(db_records)
    }
    
    for record in db_records:
        xml_path = record["xml_path"]
        if os.path.exists(xml_path):
            results["exists"].append(record)
        else:
            results["missing"].append(record)
    
    return results

def create_xml_fingerprint(record):
    """
    Create a unique fingerprint for an XML file based on its metadata
    This fingerprint survives path changes
    """
    xml_filename = os.path.basename(record["xml_path"])
    
    # For geotek-ct-stack: use parent folder name + filename
    if record["xml_root_tag"] == "geotek-ct-stack":
        parent_folder = os.path.basename(record["tiff_folder"])
        
        return {
            "core_name": record["core_name"],
            "section_number": str(record["section_number"]),
            "xml_root_tag": record["xml_root_tag"],
            "image_type": record.get("image_type", ""),
            "processing_stage": record.get("processing_stage", ""),
            "parent_folder": parent_folder,
            "xml_filename": xml_filename
        }
    
    # For geotek-image: just use the XML filename (it's unique)
    elif record["xml_root_tag"] == "geotek-image":
        return {
            "core_name": record["core_name"],
            "section_number": str(record["section_number"]),
            "xml_root_tag": record["xml_root_tag"],
            "image_type": record.get("image_type", ""),
            "xml_filename": xml_filename
        }
    
    # For geotek-xray-scan-recipe: parent folder + filename
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
    """Convert fingerprint dict to hashable string"""
    parts = [
        fp["core_name"],
        fp["section_number"],
        fp["xml_root_tag"],
        fp.get("image_type", ""),
        fp.get("processing_stage", ""),
        fp.get("parent_folder", ""),
        fp["xml_filename"]
    ]
    return "|".join(str(p) for p in parts)

def find_moved_files(ct_root, missing_records):
    """
    For missing database records, search filesystem to find where they moved to
    Uses fingerprinting to match files
    """
    # Create fingerprints for missing files
    missing_fingerprints = {}
    for record in missing_records:
        fp = create_xml_fingerprint(record)
        fp_string = fingerprint_to_string(fp)
        missing_fingerprints[fp_string] = record
    
    # Scan filesystem and create fingerprints
    st.write(f"🔍 Scanning {ct_root} for XML files...")
    disk_records = scan_ct_folders(ct_root)
    
    matches = []
    not_found = []
    
    for missing_fp_string, db_record in missing_fingerprints.items():
        found = False
        
        for disk_record in disk_records:
            disk_fp = create_xml_fingerprint(disk_record)
            disk_fp_string = fingerprint_to_string(disk_fp)
            
            if missing_fp_string == disk_fp_string:
                # Found a match!
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
    
    return {
        "matches": matches,
        "not_found": not_found
    }

def update_xml_paths(updates):
    """Update xml_path and tiff_folder for moved files, handling conflicts"""
    updated_count = 0
    skipped_count = 0
    
    with engine.begin() as conn:
        for update in updates:
            # Check if target path already exists in database
            existing = conn.execute(text("""
                SELECT id FROM ct_xml 
                WHERE xml_path = :new_path AND id != :current_id
            """), {
                "new_path": update["new_xml_path"],
                "current_id": update["id"]
            }).fetchone()
            
            if existing:
                print(f"⚠️ Skipping update for ID {update['id']}: target path already exists (ID {existing[0]})")
                print(f"   Path: {update['new_xml_path']}")
                skipped_count += 1
                continue
            
            try:
                conn.execute(text("""
                    UPDATE ct_xml
                    SET xml_path = :new_xml_path,
                        tiff_folder = :new_tiff_folder
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

# === Streamlit App ===
def main():
    st.set_page_config(page_title="CT Data Manager", layout="wide")
    st.title("🔬 CT Scan Data Manager")
    
    with st.sidebar:
        st.header("⚙️ Settings")
        ct_root = st.text_input(
            "CT Root Folder",
            value="C:\\Users\\chris\\Documents\\steen_tessin2025\\CT_Drive",
            help="Path to CT data directory"
        )
    
    tab1, tab2, tab3 = st.tabs(
        ["1️⃣ Import Scans", "2️⃣ Database View", "3️⃣ Path Maintenance"]
    )
    
    # === TAB 1: Import Scans (combines old Tab 1 + Tab 2) ===
    with tab1:
        st.header("Import CT Scans")
        st.write("""
        **Workflow for active scanning:**
        1. Scan directory for new XML files
        2. Validate Core-ID and Section-ID against database
        3. Fix any mismatches (if needed)
        4. Import directly to database
        """)
        
        if st.button("🔍 Scan Directory", use_container_width=True, type="primary"):
            with st.spinner("Scanning and validating..."):
                records = scan_ct_folders(ct_root)
                validated = validate_against_database(records)
                st.session_state.validated_records = validated
        
        if "validated_records" in st.session_state:
            validated = st.session_state.validated_records
            summary_df, summary_data = get_validation_summary(validated)
            
            # Check if we have data before calculating metrics
            if not summary_df.empty:
                # Metrics
                total = len(summary_df)
                valid = len(summary_df[summary_df["Status"] == "✅ Valid"])
                invalid = len(summary_df[summary_df["Status"] == "❌ Invalid"])
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Found", total)
                with col2:
                    st.metric("Valid", valid)
                with col3:
                    st.metric("Needs Fixing", invalid)
                
                st.dataframe(summary_df, use_container_width=True)
                
                # Show fix interface for invalid records
                if invalid > 0:
                    st.markdown("---")
                    st.subheader("🔧 Fix Invalid Records")
                    st.warning(f"⚠️ Fix {invalid} core/section combinations before importing")
                    
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
                                new_core = st.text_input(
                                    "New Core-ID",
                                    key=f"fix_core_{core}_{section}",
                                    placeholder=core
                                )
                            
                            with col2:
                                new_section = st.text_input(
                                    "New Section-ID",
                                    key=f"fix_section_{core}_{section}",
                                    placeholder=str(section)
                                )
                            
                            if new_core or new_section:
                                edit_data[(core, section)] = {
                                    "new_core": new_core,
                                    "new_section": new_section
                                }
                    
                    if edit_data:
                        st.markdown("---")
                        if st.button("💾 Apply Fixes to Invalid XMLs", use_container_width=True, type="primary", key="fix_invalid_btn"):
                            fm = CTFileManager(ct_root)
                            total_files = sum(len(summary_data[(core, section)]["records"]) 
                                             for (core, section) in edit_data.keys())
                            
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
                                        filename = os.path.basename(xml_path)
                                        
                                        status_text.text(f"Processing {current_file}/{total_files}: {filename}")
                                        
                                        success = True
                                        
                                        if changes["new_core"]:
                                            if not fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"]):
                                                success = False
                                        
                                        if changes["new_section"] and success:
                                            if not fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"]):
                                                success = False
                                            if success:
                                                fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                        
                                        if success:
                                            total_updated += 1
                                        else:
                                            total_failed += 1
                                        
                                        progress_bar.progress(current_file / total_files)
                            
                            progress_bar.empty()
                            status_text.empty()
                            
                            # Show results
                            if total_failed > 0:
                                st.warning(f"⚠️ Updated {total_updated} XML files, {total_failed} failed (check console for details)")
                            else:
                                st.success(f"✅ Successfully updated {total_updated} XML files")
                            
                            # Wait a moment so user can see the message
                            time.sleep(1.5)
                            
                            # Clear validated records and rescan automatically
                            if "validated_records" in st.session_state:
                                del st.session_state.validated_records
                            
                            st.info("🔄 Re-scanning to verify fixes...")
                            time.sleep(0.5)
                            
                            # Trigger rescan
                            records = scan_ct_folders(ct_root)
                            validated = validate_against_database(records)
                            st.session_state.validated_records = validated
                            
                            st.rerun()
                
                # Edit interface for VALID records (optional corrections)
                if valid > 0:
                    st.markdown("---")
                    st.subheader("✏️ Edit Valid Records (Optional)")
                    st.info("These records passed validation but you can still edit them if needed (e.g., wrong core name but both exist in database)")
                    
                    valid_df = summary_df[summary_df["Status"] == "✅ Valid"]
                    
                    valid_edit_data = {}
                    for idx, row in valid_df.iterrows():
                        core = row["Core"]
                        section = row["Section"]
                        xml_count = row["XML Count"]
                        
                        with st.expander(f"✏️ {core} - Section {section} ({xml_count} XMLs)"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                new_core = st.text_input(
                                    "New Core-ID",
                                    key=f"edit_core_{core}_{section}",
                                    placeholder=core
                                )
                            
                            with col2:
                                new_section = st.text_input(
                                    "New Section-ID",
                                    key=f"edit_section_{core}_{section}",
                                    placeholder=str(section)
                                )
                            
                            if new_core or new_section:
                                valid_edit_data[(core, section)] = {
                                    "new_core": new_core,
                                    "new_section": new_section
                                }
                    
                    if valid_edit_data:
                        st.markdown("---")
                        if st.button("💾 Apply Edits to Valid XMLs", use_container_width=True, type="secondary", key="edit_valid_btn"):
                            # First, validate all the new names before making any changes
                            validation_failed = False
                            validation_errors = []
                            
                            with engine.connect() as conn:
                                for (core, section), changes in valid_edit_data.items():
                                    # Validate new core name if provided
                                    if changes["new_core"]:
                                        core_exists = conn.execute(
                                            text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                                            {"core_name": changes["new_core"].strip()}
                                        ).fetchone()
                                        
                                        if not core_exists:
                                            validation_failed = True
                                            validation_errors.append(f"Core '{changes['new_core']}' does not exist in database")
                                    
                                    # Validate new section number if provided
                                    if changes["new_section"]:
                                        # Determine which core to check against
                                        check_core = changes["new_core"] if changes["new_core"] else core
                                        
                                        # Get core_id for the core we're checking
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
                            
                            # If validation failed, show errors and stop
                            if validation_failed:
                                st.error("❌ Cannot apply edits - new names are invalid:")
                                for error in validation_errors:
                                    st.error(f"  • {error}")
                                st.warning("Please correct these issues before applying edits.")
                            else:
                                # Validation passed - proceed with edits
                                fm = CTFileManager(ct_root)
                                total_files = sum(len(summary_data[(core, section)]["records"]) 
                                                 for (core, section) in valid_edit_data.keys())
                                
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                
                                total_updated = 0
                                total_failed = 0
                                current_file = 0
                                
                                for (core, section), changes in valid_edit_data.items():
                                    key = (core, section)
                                    if key in summary_data:
                                        for val in summary_data[key]["records"]:
                                            current_file += 1
                                            record = val["record"]
                                            xml_path = record["xml_path"]
                                            filename = os.path.basename(xml_path)
                                            
                                            status_text.text(f"Processing {current_file}/{total_files}: {filename}")
                                            
                                            success = True
                                            
                                            if changes["new_core"]:
                                                if not fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"]):
                                                    success = False
                                            
                                            if changes["new_section"] and success:
                                                if not fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"]):
                                                    success = False
                                                if success:
                                                    fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                            
                                            if success:
                                                total_updated += 1
                                            else:
                                                total_failed += 1
                                            
                                            progress_bar.progress(current_file / total_files)
                                
                                progress_bar.empty()
                                status_text.empty()
                                
                                # Show results
                                if total_failed > 0:
                                    st.warning(f"⚠️ Updated {total_updated} XML files, {total_failed} failed (check console for details)")
                                else:
                                    st.success(f"✅ Successfully updated {total_updated} XML files")
                                
                                # Wait a moment so user can see the message
                                time.sleep(1.5)
                                
                                # Clear validated records and rescan automatically
                                if "validated_records" in st.session_state:
                                    del st.session_state.validated_records
                                
                                st.info("🔄 Re-scanning to verify edits...")
                                time.sleep(0.5)
                                
                                # Trigger rescan
                                records = scan_ct_folders(ct_root)
                                validated = validate_against_database(records)
                                st.session_state.validated_records = validated
                                
                                st.rerun()
                
                # Import button (only show if all valid)
                if invalid == 0:
                    st.markdown("---")
                    st.success("✅ All records validated! Ready to import.")
                    
                    if st.button("📥 Import to Database", use_container_width=True, type="primary"):
                        with st.spinner("Importing to database..."):
                            saved, skipped_path, skipped_fp, failed = import_to_database(validated)
                        
                        # Show results
                        if saved > 0:
                            st.success(f"✅ Imported {saved} new XML files to database")
                        
                        if skipped_path > 0:
                            st.info(f"ℹ️ Skipped {skipped_path} files (already in database at same path)")
                        
                        if skipped_fp > 0:
                            st.warning(f"⚠️ Skipped {skipped_fp} files (same scan exists at different path)")
                            st.write("These files may have been moved. Use **Tab 3: Path Maintenance** to update their locations.")
                        
                        if failed > 0:
                            st.error(f"❌ {failed} files failed to import (check console for details)")
                        
                        # Clear session state
                        if "validated_records" in st.session_state:
                            del st.session_state.validated_records
                        
                        time.sleep(2)
                        st.rerun()
            else:
                st.warning("⚠️ No valid records found after validation")
        else:
            st.info("👆 Click 'Scan Directory' to begin")
    
    # === TAB 2: Database View (old Tab 3) ===
    with tab2:
        st.header("Database View")
        st.write("""
        **View what scans are currently in the database:**
        - **CT Stack Types**: Shows image types with their processing stages
        - **Image Types**: Shows image types from geotek-image XMLs
        """)
        
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
        
        ct_xml_df = get_ct_xml_summary()
        
        if not ct_xml_df.empty:
            st.subheader("📊 CT Scans in Database")
            st.dataframe(ct_xml_df, use_container_width=True)
            st.info(f"Total: {len(ct_xml_df)} core/section combinations in database")
            
            # Download button
            csv_data = ct_xml_df.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name="ct_xml_summary.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # Detailed view
            with st.expander("📋 View Detailed Records"):
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT 
                            core_name,
                            section_number,
                            xml_root_tag,
                            scan_id,
                            image_type,
                            processing_stage,
                            xml_path
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

    # === TAB 3: Path Maintenance (old Tab 4) ===
    with tab3:
        st.header("Path Maintenance")
        st.write("""
        **Use this after reorganizing files or moving between hard drives:**
        1. Check which database records point to missing files
        2. Search filesystem to find where files moved to
        3. Update database with new paths
        
        ⚠️ You shouldn't need this during normal scanning - only when reorganizing existing data.
        """)
        
        if st.button("🔍 Check for Missing Files", use_container_width=True, type="primary"):
            with st.spinner("Verifying paths..."):
                verification = verify_xml_paths(ct_root)
                st.session_state.path_verification = verification
        
        if "path_verification" in st.session_state and st.session_state.path_verification is not None:
            verify = st.session_state.path_verification
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Records", verify["total"])
            with col2:
                st.metric("✅ Found", len(verify["exists"]))
            with col3:
                st.metric("❌ Missing", len(verify["missing"]))
            
            if verify["missing"]:
                st.markdown("---")
                st.warning(f"⚠️ {len(verify['missing'])} XML files not found at recorded paths")
                
                # Show missing files
                with st.expander("📋 View Missing Files"):
                    missing_df = pd.DataFrame(verify["missing"])
                    if not missing_df.empty:
                        display_cols = ["core_name", "section_number", "xml_root_tag", "image_type", "xml_path"]
                        st.dataframe(missing_df[display_cols], use_container_width=True)
                
                st.markdown("---")
                st.subheader("🔍 Search for Moved Files")
                st.info("This will scan the filesystem to find where these files moved to")
                
                if st.button("🔎 Search for Moved Files", use_container_width=True, type="primary"):
                    with st.spinner(f"Searching {ct_root} for {len(verify['missing'])} missing files..."):
                        search_results = find_moved_files(ct_root, verify["missing"])
                        st.session_state.path_search_results = search_results
                
                if "path_search_results" in st.session_state and st.session_state.path_search_results is not None:
                    results = st.session_state.path_search_results
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("✅ Found", len(results["matches"]))
                    with col2:
                        st.metric("❌ Not Found", len(results["not_found"]))
                    
                    if results["matches"]:
                        st.success(f"🎉 Found {len(results['matches'])} moved files!")
                        
                        # Show matches
                        with st.expander("📋 View Path Changes", expanded=True):
                            for match in results["matches"][:10]:  # Show first 10
                                st.write(f"**{match['core_name']} - Section {match['section_number']} - {match['xml_root_tag']}**")
                                st.text(f"  Old: {match['old_xml_path']}")
                                st.text(f"  New: {match['new_xml_path']}")
                                st.text("")
                            
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
                            
                            # Clear session state before rerun
                            if "path_verification" in st.session_state:
                                del st.session_state.path_verification
                            if "path_search_results" in st.session_state:
                                del st.session_state.path_search_results
                            st.rerun()
                    
                    if results["not_found"]:
                        st.error(f"❌ Could not find {len(results['not_found'])} files")
                        st.write("These files may have been deleted or have different metadata")
                        
                        with st.expander("📋 View Files Not Found"):
                            not_found_df = pd.DataFrame(results["not_found"])
                            if not not_found_df.empty:
                                display_cols = ["core_name", "section_number", "xml_root_tag", "xml_path"]
                                st.dataframe(not_found_df[display_cols], use_container_width=True)
            
            else:
                st.success("✅ All XML files found at their recorded paths!")
        else:
            st.info("👆 Click 'Check for Missing Files' to begin")


if __name__ == "__main__":
    main()

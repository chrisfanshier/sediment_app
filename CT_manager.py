import os
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

# === Database Setup ===
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
        return data
    except Exception as e:
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
            
            found = False
            for elem in root.iter():
                if elem.tag.lower() == field_name.lower():
                    old_value = elem.text
                    elem.text = new_value
                    found = True
                    print(f"Updated {elem.tag}: '{old_value}' → '{new_value}' in {os.path.basename(full_path)}")
                    break
        
            if found:
                tree.write(full_path, encoding='utf-8', xml_declaration=True)
                return True
            else:
                print(f"Field '{field_name}' not found in {full_path}")
                return False
            
        except Exception as e:
            print(f"Error editing XML {full_path}: {e}")
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

# === PHASE 2: Save to Staging ===
def save_to_staging(validated_records):
    """Save validated records to staging table, skipping records already in staging OR ct_xml"""
    saved_count = 0
    skipped_count = 0
    
    with engine.begin() as conn:
        # Get existing XMLs in staging
        existing_in_staging = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml_staging"))
        )
        
        # Get existing XMLs in main ct_xml table
        existing_in_ct_xml = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml"))
        )
        
        # Combined set of all existing XMLs
        all_existing = existing_in_staging | existing_in_ct_xml
        
        for val in validated_records:
            if val["status"] != "valid":
                skipped_count += 1
                continue
            
            record = val["record"]
            
            # Skip if already in staging OR already in ct_xml
            if record["xml_path"] in all_existing:
                skipped_count += 1
                continue
            
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
            
            # Insert to staging
            conn.execute(
                text("""
                    INSERT INTO ct_xml_staging (
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
    
    return saved_count, skipped_count

def get_staging_summary():
    """Get summary of what's in staging"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                core_name,
                section_number,
                COUNT(*) as xml_count,
                STRING_AGG(DISTINCT scan_id, ', ') as scan_types,
                STRING_AGG(DISTINCT processing_stage, ', ') as stages
            FROM ct_xml_staging
            GROUP BY core_name, section_number
            ORDER BY core_name, section_number
        """))
        rows = [dict(row._mapping) for row in result.fetchall()]
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df.columns = ["Core", "Section", "XML Count", "Scan Types", "Processing Stages"]
    
    return df

def approve_and_import_staging():
    """Move all records from staging to ct_xml, skipping duplicates"""
    with engine.begin() as conn:
        # Insert only records that don't already exist in ct_xml
        result = conn.execute(text("""
            INSERT INTO ct_xml 
            SELECT s.* 
            FROM ct_xml_staging s
            WHERE NOT EXISTS (
                SELECT 1 
                FROM ct_xml c 
                WHERE c.xml_path = s.xml_path
            )
        """))
        
        inserted_count = result.rowcount
        
        # Delete all from staging (including duplicates that weren't inserted)
        conn.execute(text("DELETE FROM ct_xml_staging"))
        
        return inserted_count

# === PHASE 3: View ct_xml table ===
def get_ct_xml_summary():
    """Get summary of what's in ct_xml with separate columns for CT Stack and Image data"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                core_name,
                section_number,
                COUNT(*) as xml_count,
                -- CT Stack data (has processing stages)
                STRING_AGG(
                    DISTINCT CASE 
                        WHEN xml_root_tag = 'geotek-ct-stack' 
                        THEN image_type || ' (' || processing_stage || ')' 
                    END, 
                    ', '
                ) as ct_stack_data,
                -- Image data (no processing stages)
                STRING_AGG(
                    DISTINCT CASE 
                        WHEN xml_root_tag = 'geotek-image' 
                        THEN image_type 
                    END, 
                    ', '
                ) as image_data
            FROM ct_xml
            GROUP BY core_name, section_number
            ORDER BY core_name, section_number
        """))
        rows = [dict(row._mapping) for row in result.fetchall()]
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df.columns = ["Core", "Section", "Total XMLs", "CT Stack Types", "Image Types"]
    
    # Replace None with empty string for cleaner display
    df["CT Stack Types"] = df["CT Stack Types"].fillna("")
    df["Image Types"] = df["Image Types"].fillna("")
    
    return df

# Add this new function after get_ct_xml_summary()

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
        # Parent folder like "A_Radiography_raw_A00000"
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
                    "id": db_record["id"],  # Changed from xml_id to id
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
    """Update xml_path and tiff_folder for moved files"""
    with engine.begin() as conn:
        for update in updates:
            conn.execute(text("""
                UPDATE ct_xml
                SET xml_path = :new_xml_path,
                    tiff_folder = :new_tiff_folder
                WHERE id = :id
            """), {
                "id": update["id"],  # Changed from xml_id to id
                "new_xml_path": update["new_xml_path"],
                "new_tiff_folder": update["new_tiff_folder"]
            })
    return len(updates)

def bulk_replace_path_prefix(old_prefix, new_prefix):
    """Replace path prefix for all records (useful when moving entire drive)"""
    with engine.begin() as conn:
        # Update xml_path
        result = conn.execute(text("""
            UPDATE ct_xml
            SET xml_path = REPLACE(xml_path, :old_prefix, :new_prefix),
                tiff_folder = REPLACE(tiff_folder, :old_prefix, :new_prefix)
            WHERE xml_path LIKE :pattern
        """), {
            "old_prefix": old_prefix,
            "new_prefix": new_prefix,
            "pattern": f"{old_prefix}%"
        })
        return result.rowcount

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
    
    tab1, tab2, tab3, tab4 = st.tabs(
        ["1️⃣ Validate Metadata", "2️⃣ Staging & Import", "3️⃣ Database View", "4️⃣ Path Updates"]
    )
    
    # === TAB 1: Validate Metadata ===
    with tab1:
        st.header("Phase 1: Validate Metadata Against Database")
        st.write("""
        **This is the critical first step:**
        1. Scan folder for XML files
        2. Check if Core-ID and Section-ID exist in database
        3. Fix any mismatches before proceeding
        """)
        
        if st.button("🔍 Scan & Validate", use_container_width=True, type="primary"):
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
                    st.metric("Total Core/Section Combos", total)
                with col2:
                    st.metric("✅ Valid", valid, delta=None, delta_color="normal")
                with col3:
                    st.metric("❌ Invalid", invalid, delta=None, delta_color="inverse")
                
                st.dataframe(summary_df, use_container_width=True)
                
                # Show fix interface for invalid records
                if invalid > 0:
                    st.markdown("---")
                    st.subheader("🔧 Fix Invalid Records")
                    st.warning(f"You must fix {invalid} core/section combinations before importing")
                    
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
                        if st.button("💾 Apply Fixes to XML Files", use_container_width=True, type="primary"):
                            with st.spinner("Updating XML files..."):
                                fm = CTFileManager(ct_root)
                                total_updated = 0
                                
                                for (core, section), changes in edit_data.items():
                                    key = (core, section)
                                    if key in summary_data:
                                        for val in summary_data[key]["records"]:
                                            record = val["record"]
                                            xml_path = record["xml_path"]
                                            
                                            if changes["new_core"]:
                                                fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"])
                                            
                                            if changes["new_section"]:
                                                fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"])
                                                fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                            
                                            total_updated += 1
                                
                                st.success(f"✅ Updated {total_updated} XML files")
                                st.info("🔄 Click 'Scan & Validate' again to verify fixes")
                                st.session_state.validated_records = None
                                st.rerun()
                
                # Allow proceeding to staging
                if invalid == 0:
                    st.markdown("---")
                    st.success("✅ All metadata is valid! Ready to save to staging.")
                    
                    if st.button("➡️ Save to Staging", use_container_width=True, type="primary"):
                        with st.spinner("Saving to staging..."):
                            saved, skipped = save_to_staging(validated)
                            st.success(f"✅ Saved {saved} new records to staging")
                            if skipped > 0:
                                st.info(f"Skipped {skipped} (already in staging or invalid)")
                            st.session_state.validated_records = None
                            st.rerun()
            else:
                st.warning("⚠️ No valid records found after validation")
        else:
            st.info("👆 Click 'Scan & Validate' to begin")
    
    # === TAB 2: Staging ===
    with tab2:
        st.header("Phase 2: Review Staging & Import to Database")
        st.write("""
        **Review what will be imported:**
        - View all core/section combinations in staging
        - See scan types and processing stages
        - Import to main ct_xml table when ready
        """)
        
        staging_df = get_staging_summary()
        
        if not staging_df.empty:
            st.subheader("📋 Staging Summary")
            st.dataframe(staging_df, use_container_width=True)
            st.info(f"Total: {len(staging_df)} core/section combinations")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("✅ Import All to ct_xml", use_container_width=True, type="primary"):
                    with st.spinner("Importing to ct_xml..."):
                        imported_count = approve_and_import_staging()
                        if imported_count > 0:
                            st.success(f"✅ Successfully imported {imported_count} new records!")
                        else:
                            st.info("ℹ️ All staging records already exist in ct_xml. Nothing imported.")
                        st.rerun()
            
            with col2:
                if st.button("🗑️ Clear Staging", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM ct_xml_staging"))
                    st.success("Staging cleared")
                    st.rerun()
            
            with col3:
                csv_data = staging_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name="ct_staging.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            # Detailed view
            with st.expander("📋 View Detailed Records"):
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT * FROM ct_xml_staging ORDER BY core_name, section_number"))
                    detailed = [dict(row._mapping) for row in result.fetchall()]
                
                if detailed:
                    st.dataframe(pd.DataFrame(detailed), use_container_width=True)
        else:
            st.info("No records in staging. Validate and save from Tab 1 first.")
    
    # === TAB 3: Database View ===
    with tab3:
        st.header("Phase 3: Database View")
        st.write("""
        **View what's currently in the ct_xml table:**
        - **CT Stack Types**: Shows image types with their processing stages
        - **Image Types**: Shows image types from geotek-image XMLs
        """)
        
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
        
        ct_xml_df = get_ct_xml_summary()
        
        if not ct_xml_df.empty:
            st.subheader("📊 ct_xml Table Summary")
            
            # Add dropdown filter for core name
            all_cores = ["All Cores"] + sorted(ct_xml_df["Core"].unique().tolist())
            selected_core = st.selectbox("Filter by Core:", all_cores, key="summary_core_filter")
            
            # Filter dataframe based on selection
            if selected_core != "All Cores":
                filtered_df = ct_xml_df[ct_xml_df["Core"] == selected_core]
            else:
                filtered_df = ct_xml_df
            
            st.dataframe(filtered_df, use_container_width=True)
            st.info(f"Showing: {len(filtered_df)} core/section combinations")
            
            # Download button
            csv_data = filtered_df.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name="ct_xml_summary.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            # Detailed view with filters
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
                    
                    # Add filters for detailed view
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        detail_cores = ["All Cores"] + sorted(detail_df["Core"].unique().tolist())
                        detail_selected_core = st.selectbox("Filter by Core:", detail_cores, key="detail_core_filter")
                    
                    # Filter by core first
                    if detail_selected_core != "All Cores":
                        detail_filtered = detail_df[detail_df["Core"] == detail_selected_core]
                    else:
                        detail_filtered = detail_df
                    
                    with col2:
                        # Get sections available for selected core (keep as original type)
                        available_sections = sorted(detail_filtered["Section"].unique().tolist())
                        detail_sections = ["All Sections"] + available_sections  # Don't convert to string
                        detail_selected_section = st.selectbox("Filter by Section:", detail_sections, key="detail_section_filter")
                    
                    # Filter by section - no conversion needed!
                    if detail_selected_section != "All Sections":
                        detail_filtered = detail_filtered[detail_filtered["Section"] == detail_selected_section]
                    
                    st.dataframe(detail_filtered, use_container_width=True)
                    st.info(f"Showing: {len(detail_filtered)} records")
                    
                    # Download filtered detailed data
                    detail_csv = detail_filtered.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Detailed CSV",
                        data=detail_csv,
                        file_name="ct_xml_detailed.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key="download_detailed"
                    )
        else:
            st.info("No records in ct_xml table yet. Import from staging first.")

    # === TAB 4: Path Updates ===
    with tab4:
        st.header("Phase 4: Update Paths After Reorganization")
        
        # Add a new section at the top for bulk path replacement
        st.subheader("🔄 Bulk Path Replacement")
        st.write("**Use this when you move the entire root directory to a new location**")
        
        with st.expander("🚚 Replace Root Path (e.g., C:\\ → E:\\)"):
            col1, col2 = st.columns(2)
            
            with col1:
                old_root = st.text_input(
                    "Old Root Path",
                    value="C:\\Users\\chris\\Documents\\steen_tessin2025\\CT_Drive",
                    help="The old root path prefix to replace"
                )
            
            with col2:
                new_root = st.text_input(
                    "New Root Path",
                    value="E:\\CT_Drive",
                    help="The new root path prefix"
                )
            
            st.warning("⚠️ This will update ALL records in the database. Make sure the paths are correct!")
            
            # Preview what will change
            if st.button("🔍 Preview Changes", key="preview_bulk_replace"):
                with engine.connect() as conn:
                    preview = conn.execute(text("""
                        SELECT xml_path 
                        FROM ct_xml 
                        WHERE xml_path LIKE :pattern
                        LIMIT 5
                    """), {"pattern": f"{old_root}%"}).fetchall()
                    
                    if preview:
                        st.write("**Example changes (first 5):**")
                        for row in preview:
                            old_path = row[0]
                            new_path = old_path.replace(old_root, new_root)
                            st.text(f"Old: {old_path}")
                            st.text(f"New: {new_path}")
                            st.text("")
                        
                        # Count total affected
                        count_result = conn.execute(text("""
                            SELECT COUNT(*) 
                            FROM ct_xml 
                            WHERE xml_path LIKE :pattern
                        """), {"pattern": f"{old_root}%"}).fetchone()
                        
                        st.info(f"📊 Total records to update: {count_result[0]}")
                    else:
                        st.warning("No records found with that path prefix")
            
            if st.button("💾 Apply Bulk Path Replacement", type="primary", key="apply_bulk_replace"):
                if old_root and new_root and old_root != new_root:
                    with st.spinner("Updating paths..."):
                        count = bulk_replace_path_prefix(old_root, new_root)
                    st.success(f"✅ Updated {count} records")
                    
                    # Verify by checking a few
                    with engine.connect() as conn:
                        sample = conn.execute(text("""
                            SELECT xml_path 
                            FROM ct_xml 
                            WHERE xml_path LIKE :pattern
                            LIMIT 3
                        """), {"pattern": f"{new_root}%"}).fetchall()
                        
                        if sample:
                            st.write("**Verification (first 3 updated paths):**")
                            for row in sample:
                                st.text(row[0])
                else:
                    st.error("Please enter valid old and new root paths")
        
        st.markdown("---")
        
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
                st.metric("✅ Found", len(verify["exists"]), delta_color="normal")
            with col3:
                st.metric("❌ Missing", len(verify["missing"]), delta_color="inverse")
            
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
                                count = update_xml_paths(results["matches"])
                            st.success(f"✅ Updated {count} records in database")
                            # Clear session state before rerun
                            del st.session_state.path_verification
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
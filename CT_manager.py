import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
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
    """Handles file operations: moving, renaming, backing up CT scan files"""
    
    def __init__(self, ct_root):
        self.ct_root = ct_root
    
    def get_dir_size(self, path):
        """Calculate total directory size in GB"""
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
        return total / (1024**3)
    
    def list_directories(self, path=None):
        """List subdirectories for selection"""
        browse_path = path if path else self.ct_root
        if not os.path.exists(browse_path):
            return []
        try:
            items = os.listdir(browse_path)
            dirs = [d for d in items if os.path.isdir(os.path.join(browse_path, d))]
            return sorted(dirs)
        except Exception as e:
            return []
    
    def edit_xml_field(self, xml_path, field_name, new_value):
        """Edit a specific field in an XML file"""
        # xml_path is now absolute, don't join with ct_root
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
    
    def backup_to_drive(self, source_path, backup_drive_path):
        """Backup files to external drive"""
        src = os.path.join(self.ct_root, source_path)
        try:
            if os.path.isfile(src):
                shutil.copy2(src, backup_drive_path)
            elif os.path.isdir(src):
                shutil.copytree(src, backup_drive_path, dirs_exist_ok=True)
            return True
        except Exception as e:
            return False
    
    def move_to_drive(self, source_path, destination_drive_path):
        """Move files to different internal drive"""
        src = os.path.join(self.ct_root, source_path)
        try:
            if os.path.exists(src):
                shutil.move(src, destination_drive_path)
                return True
        except Exception as e:
            return False

# === Folder Scanning ===
def scan_ct_folders(ct_root):
    """Scan CT folders for XML files"""
    found = []
    for root, dirs, files in os.walk(ct_root):
        xmls = [f for f in files if f.lower().endswith(".xml")]
        for xml_file in xmls:
            xml_path = os.path.join(root, xml_file)
            meta = parse_ct_xml(xml_path)
            if meta and meta["core_name"]:
                # Store ABSOLUTE path in xml_path for later use
                record = {
                    **meta,
                    "xml_path": xml_path,  # Store absolute path
                    "tiff_folder": root,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                found.append(record)
    return found

def save_ct_folders_to_staging(records):
    """Save scanned records to staging table"""
    with engine.begin() as conn:
        existing_xmls = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml_staging"))
        )
        new_records = []
        for r in records:
            if r["xml_path"] in existing_xmls:
                continue
            
            core_name = r["core_name"].strip() if r["core_name"] else None
            core_row = conn.execute(
                text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                {"core_name": core_name}
            ).fetchone()
            core_id = core_row[0] if core_row else None

            section_id = None
            section_number = r["section_number"]
            try:
                section_number_int = int(section_number)
            except (TypeError, ValueError):
                section_number_int = None

            if core_id and section_number_int is not None:
                section_row = conn.execute(
                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                    {"core_id": core_id, "section_number": section_number_int}
                ).fetchone()
                if not section_row:
                    try:
                        section_length = float(r.get("total_scanned_length")) if r.get("total_scanned_length") else None
                    except Exception:
                        section_length = None
                    result = conn.execute(
                        text("""
                            INSERT INTO sections (core_id, section_number, section_length, remarks)
                            VALUES (:core_id, :section_number, :section_length, :remarks)
                            RETURNING section_id
                        """),
                        {
                            "core_id": core_id,
                            "section_number": section_number_int,
                            "section_length": section_length,
                            "remarks": "section created by ct data"
                        }
                    )
                    section_id = result.scalar()
                else:
                    section_id = section_row[0]

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
                    core_id=core_id, core_name=r["core_name"], section_id=section_id,
                    scan_id=r["scan_id"], image_type=r["image_type"],
                    processing_stage=r["processing_stage"], section_number=section_number,
                    xml_path=r["xml_path"], tiff_folder=r["tiff_folder"],
                    xml_root_tag=r["xml_root_tag"], timestamp=r["timestamp"]
                )
            )
            new_records.append(r)
        return new_records

def approve_and_import_staging():
    """Move all records from staging to ct_xml"""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ct_xml 
            SELECT * FROM ct_xml_staging
        """))
        conn.execute(text("DELETE FROM ct_xml_staging"))

def validate_record(record):
    """Return validation issues - check if core and section exist in DB"""
    issues = []
    
    if not record["core_name"]:
        issues.append("❌ Missing core_name")
        return issues
    
    if not record["section_id"]:
        issues.append("❌ Missing section_id")
        return issues
    
    # Check if core_name exists in database
    with engine.connect() as conn:
        core_row = conn.execute(
            text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
            {"core_name": record["core_name"].strip()}
        ).fetchone()
    
    if not core_row:
        issues.append(f"❌ Core '{record['core_name']}' not found in database")
        return issues
    
    core_id = core_row[0]
    
    # Try to convert section_id to int
    try:
        section_number_int = int(record["section_id"])
    except (TypeError, ValueError):
        issues.append(f"❌ Section ID '{record['section_id']}' is not a valid number")
        return issues
    
    # Check if section exists for this core
    with engine.connect() as conn:
        section_row = conn.execute(
            text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
            {"core_id": core_id, "section_number": section_number_int}
        ).fetchone()
    
    if not section_row:
        issues.append(f"❌ Section {section_number_int} not found for core '{record['core_name']}'")
    
    return issues

def get_staging_summary():
    """Get summary view of staging records grouped by core/section"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT
                   core_name,
                   section_number,
                   scan_id,
                   image_type,
                   processing_stage
            FROM ct_xml_staging
            ORDER BY core_name, section_number
        """))
        staging_data = [dict(row._mapping) for row in result.fetchall()]
    
    if not staging_data:
        return pd.DataFrame()
    
    df = pd.DataFrame(staging_data)
    
    summary_rows = []
    all_pairs = df[["core_name", "section_number"]].drop_duplicates()
    
    for _, row in all_pairs.iterrows():
        core = row["core_name"]
        section = row["section_number"]
        subdf = df[(df["core_name"] == core) & (df["section_number"] == section)]
        
        # Directories column - get unique Scan-ID values with their processing stages
        directories = []
        for scan_id in subdf["scan_id"].dropna().unique():
            stages = subdf.loc[subdf["scan_id"] == scan_id, "processing_stage"].dropna().unique()
            if len(stages) > 0:
                stage_list = ", ".join(sorted(stages))
                directories.append(f"{scan_id} ({stage_list})")
        directories_str = "; ".join(directories) if directories else "—"
        
        # Images column - get unique image types
        images = subdf["image_type"].dropna().unique()
        images_str = ", ".join(sorted(images)) if len(images) > 0 else "—"
        
        summary_rows.append({
            "Core": core,
            "Section": section,
            "Directories": directories_str,
            "Images": images_str
        })
    
    summary = pd.DataFrame(summary_rows)
    return summary

def get_scan_summary(records):
    """Create summary of scanned records: core/section with XML file counts and DB match status"""
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    summary_rows = []
    
    # Group by core_name and section_number
    grouped = df.groupby(["core_name", "section_number"])
    
    for (core_name, section_number), group in grouped:
        xml_count = len(group)
        
        # Check if this combo exists in database
        match_status = "✅ Match"
        issues = []
        
        # Validate using same logic as validate_record
        with engine.connect() as conn:
            # Check core
            core_row = conn.execute(
                text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                {"core_name": core_name.strip()}
            ).fetchone()
            
            if not core_row:
                match_status = "❌ No Match"
                issues.append("Core not found")
            else:
                core_id = core_row[0]
                
                # Check section
                try:
                    section_number_int = int(section_number)
                    section_row = conn.execute(
                        text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                        {"core_id": core_id, "section_number": section_number_int}
                    ).fetchone()
                    
                    if not section_row:
                        match_status = "❌ No Match"
                        issues.append("Section not found")
                except (TypeError, ValueError):
                    match_status = "❌ No Match"
                    issues.append("Invalid section number")
        
        summary_rows.append({
            "Core": core_name,
            "Section": section_number,
            "XML Count": xml_count,
            "DB Match": match_status,
            "Issues": "; ".join(issues) if issues else ""
        })
    
    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(["Core", "Section"])
    
    return summary

# === Streamlit App ===
def main():
    st.set_page_config(page_title="CT Crawler", layout="wide")
    st.title("🔬 CT Scan Crawler & File Manager")
    
    # Sidebar for settings only
    with st.sidebar:
        st.header("⚙️ Settings")
        ct_root = st.text_input(
            "CT Root Folder",
            value="/home/server/project/marssam/marssam_data_files/CT_Data",
            help="Path to CT data directory"
        )
    
    # Main tabs - simplified to 3 tabs
    tab1, tab2, tab3 = st.tabs(
        ["📂 Scan & Review", "📋 Staging Records", "💾 Backup/Transfer"]
    )
    
    # === TAB 1: Scan & Review ===
    with tab1:
        st.header("Scan & Review Records")
        st.write("Scan folder → Review core/section combinations → Fix mismatches → Approve to Staging")
        
        if st.button("🔍 Scan CT Folders", use_container_width=True, key="scan_btn"):
            with st.spinner("Scanning CT folders..."):
                records = scan_ct_folders(ct_root)
                st.session_state.scan_records = records
        
        if "scan_records" in st.session_state and st.session_state.scan_records:
            records = st.session_state.scan_records
            st.success(f"✅ Found {len(records)} total XML files")
            
            # Show summary table
            st.subheader("📊 Core/Section Summary")
            summary_df = get_scan_summary(records)
            
            # Count mismatches
            mismatch_count = len(summary_df[summary_df["DB Match"] == "❌ No Match"])
            match_count = len(summary_df[summary_df["DB Match"] == "✅ Match"])
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Matched Combinations", match_count)
            with col2:
                st.metric("Need Fixing", mismatch_count)
            
            # Display the summary table
            st.dataframe(summary_df, use_container_width=True)
            
            # If there are mismatches, show bulk edit interface
            if mismatch_count > 0:
                st.markdown("---")
                st.subheader("🔧 Bulk Fix Mismatches")
                st.write("Enter new values for core/section combinations that don't match the database:")
                
                # Get mismatched rows
                mismatched_df = summary_df[summary_df["DB Match"] == "❌ No Match"]
                
                # Create input fields for each mismatched combo
                edit_data = {}
                for idx, row in mismatched_df.iterrows():
                    core = row["Core"]
                    section = row["Section"]
                    issues = row["Issues"]
                    xml_count = row["XML Count"]
                    
                    with st.expander(f"🔧 {core} - Section {section} ({xml_count} XMLs) - {issues}"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            new_core = st.text_input(
                                "New Core-ID (leave blank to skip)",
                                key=f"bulk_core_{core}_{section}",
                                placeholder=core
                            )
                        
                        with col2:
                            new_section = st.text_input(
                                "New Section-ID (leave blank to skip)",
                                key=f"bulk_section_{core}_{section}",
                                placeholder=str(section)
                            )
                        
                        if new_core or new_section:
                            edit_data[(core, section)] = {
                                "new_core": new_core,
                                "new_section": new_section
                            }
                
                # Bulk update button
                if edit_data:
                    st.markdown("---")
                    if st.button("💾 Update All Modified Entries", use_container_width=True, type="primary"):
                        with st.spinner("Updating XML files..."):
                            fm = CTFileManager(ct_root)
                            total_updated = 0
                            total_errors = []
                            
                            # Get all XMLs for the combos that need updating
                            for (core, section), changes in edit_data.items():
                                # Find all XML files for this core/section combo
                                matching_records = [
                                    r for r in records 
                                    if r["core_name"] == core and str(r["section_number"]) == str(section)
                                ]
                                
                                for record in matching_records:
                                    xml_path = record["xml_path"]
                                    try:
                                        if changes["new_core"]:
                                            fm.edit_xml_field(xml_path, "Core-ID", changes["new_core"])
                                        
                                        if changes["new_section"]:
                                            fm.edit_xml_field(xml_path, "Section-ID", changes["new_section"])
                                            fm.edit_xml_field(xml_path, "Section-Number", changes["new_section"])
                                        
                                        total_updated += 1
                                    except Exception as e:
                                        total_errors.append(f"{os.path.basename(xml_path)}: {str(e)}")
                            
                            if total_updated > 0:
                                st.success(f"✅ Successfully updated {total_updated} XML files")
                            
                            if total_errors:
                                st.error(f"❌ {len(total_errors)} errors occurred:")
                                for err in total_errors[:10]:  # Show first 10 errors
                                    st.text(f"  • {err}")
                                if len(total_errors) > 10:
                                    st.text(f"  ... and {len(total_errors) - 10} more errors")
                            
                            # Clear session and prompt rescan
                            st.info("🔄 Click 'Scan CT Folders' again to see updated results")
                            st.session_state.scan_records = None
                            st.rerun()
            
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approve & Save to Staging", use_container_width=True):
                    with st.spinner("Saving to staging..."):
                        new_records = save_ct_folders_to_staging(records)
                        st.success(f"✅ Saved {len(new_records)} XML files to staging")
                        st.info(f"Skipped {len(records) - len(new_records)} (already exist)")
                        st.session_state.scan_records = None
                        st.rerun()
            
            with col2:
                if st.button("🔄 Clear & Rescan", use_container_width=True):
                    st.session_state.scan_records = None
                    st.rerun()
        else:
            st.info("Click 'Scan CT Folders' to begin")
    
    # === TAB 2: Staging Records ===
    with tab2:
        st.header("Staging Records - Summary View")
        st.write("One row per core/section showing all directories and image types")
        
        summary_df = get_staging_summary()
        
        if not summary_df.empty:
            st.dataframe(summary_df, use_container_width=True)
            st.info(f"Total core/section combinations: {len(summary_df)}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("✅ Approve All & Import", use_container_width=True):
                    with st.spinner("Importing..."):
                        approve_and_import_staging()
                        st.success("✅ Imported all staging records to ct_xml")
                        st.rerun()
            
            with col2:
                if st.button("🗑️ Clear Staging", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM ct_xml_staging"))
                    st.success("Staging table cleared")
                    st.rerun()
            
            with col3:
                csv_data = summary_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name="ct_staging_summary.csv",
                    mime="text/csv"
                )
            
            # Show detailed records in expandable section
            with st.expander("📋 View All Individual Records"):
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT * FROM ct_xml_staging ORDER BY core_name, section_number"))
                    detailed_rows = [dict(row._mapping) for row in result.fetchall()]
                
                if detailed_rows:
                    detailed_df = pd.DataFrame(detailed_rows)
                    st.dataframe(detailed_df, use_container_width=True)
        else:
            st.info("No staging records. Scan and approve from Tab 1 first.")
    
    # === TAB 3: Backup/Transfer ===
    with tab3:
        st.header("Backup & Transfer Large Files")
        st.write("Transfer CT scan folders to external or internal drives")
        
        fm = CTFileManager(ct_root)
        
        operation = st.radio("Operation Type", ["Backup to External Drive", "Move to Internal Drive"])
        
        st.subheader("Select Source Directory")
        dirs = fm.list_directories()
        if dirs:
            source_dir = st.selectbox("Source subdirectory", options=dirs)
            source_full = os.path.join(ct_root, source_dir)
            size_gb = fm.get_dir_size(source_full)
            st.info(f"📊 Directory size: **{size_gb:.2f} GB**")
        else:
            st.error("No directories found in CT root folder")
            source_dir = None
        
        st.subheader("Destination Path")
        dest_path = st.text_input(
            "Full destination path",
            placeholder="E:\\CT_Backup\\2024_Scans"
        )
        
        if st.button(f"💾 Start {operation.split()[0]}", use_container_width=True):
            if not source_dir or not dest_path:
                st.error("Please select source and enter destination")
            else:
                with st.spinner(f"Transferring {size_gb:.2f} GB... This may take several minutes."):
                    try:
                        if "External" in operation:
                            success = fm.backup_to_drive(source_dir, dest_path)
                        else:
                            success = fm.move_to_drive(source_dir, dest_path)
                        
                        if success:
                            st.success(f"✅ Transfer complete!")
                            st.info(f"Source: {source_dir}\nDestination: {dest_path}")
                        else:
                            st.error("❌ Transfer failed. Check paths and permissions.")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
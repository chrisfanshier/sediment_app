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
    """Save validated records to staging table"""
    saved_count = 0
    skipped_count = 0
    
    with engine.begin() as conn:
        # Get existing XMLs in staging
        existing_xmls = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml_staging"))
        )
        
        for val in validated_records:
            if val["status"] != "valid":
                skipped_count += 1
                continue
            
            record = val["record"]
            
            if record["xml_path"] in existing_xmls:
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
    """Get summary of what's in ct_xml (same format as staging)"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                core_name,
                section_number,
                COUNT(*) as xml_count,
                STRING_AGG(DISTINCT scan_id, ', ') as scan_types,
                STRING_AGG(DISTINCT processing_stage, ', ') as stages
            FROM ct_xml
            GROUP BY core_name, section_number
            ORDER BY core_name, section_number
        """))
        rows = [dict(row._mapping) for row in result.fetchall()]
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df.columns = ["Core", "Section", "XML Count", "Scan Types", "Processing Stages"]
    
    return df

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
        ["1️⃣ Validate Metadata", "2️⃣ Staging & Import", "3️⃣ Database View"]
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
        - Same summary view as staging
        - Shows all imported CT scan metadata
        """)
        
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
        
        ct_xml_df = get_ct_xml_summary()
        
        if not ct_xml_df.empty:
            st.subheader("📊 ct_xml Table Summary")
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
                    result = conn.execute(text("SELECT * FROM ct_xml ORDER BY core_name, section_number"))
                    detailed = [dict(row._mapping) for row in result.fetchall()]
                
                if detailed:
                    st.dataframe(pd.DataFrame(detailed), use_container_width=True)
        else:
            st.info("No records in ct_xml table yet. Import from staging first.")

if __name__ == "__main__":
    main()
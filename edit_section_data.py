import streamlit as st
import pandas as pd
from db_util import (get_cores_with_sections, get_sections_for_core, 
                     delete_all_sections_for_core, insert_section, update_section, delete_section)
import psycopg2

st.title("✏️ Edit Section Data")

# Main interface
cores_with_sections = get_cores_with_sections(only_created_on_ship=True)

if not cores_with_sections:
    st.warning("No cores with sections found. Please add sections first using the 'Add Section Data' page.")
else:
    # Step 1: Select Core
    st.subheader("Select Core to Edit")
    core_options = {f"{name} ({cruise_name}) - {count} sections": (id, name, cruise_name, count) 
                for id, name, cruise_name, count in cores_with_sections}
    selected_core_label = st.selectbox("Select Core", [""] + list(core_options.keys()))
    
    if selected_core_label:
        selected_core_id, selected_core_name, selected_cruise_name, section_count = core_options[selected_core_label]

        # Get existing sections
        existing_sections = get_sections_for_core(selected_core_id)
        
        st.subheader(f"Edit Sections for {selected_core_name}")
        st.write(f"**Cruise:** {selected_cruise_name}")
        
        # Initialize session state for section lengths
        if "section_lengths" not in st.session_state or st.session_state.get("current_core_id") != selected_core_id:
            st.session_state.section_lengths = []
            st.session_state.current_core_id = selected_core_id
            # Load existing section lengths
            for section in existing_sections:
                section_id, section_number, section_length, *_ = section
                st.session_state.section_lengths.append(float(section_length or 0))
        
        st.write("**Edit section lengths (in cm). Section numbers will auto-renumber.**")
        
        # Display current sections in an editable format
        sections_data = []
        total_length = 0
        
        for i, length in enumerate(st.session_state.section_lengths):
            col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 1, 1])
            
            with col1:
                st.write(f"**{i+1}**")  # Auto-numbered sections
            
            with col2:
                new_length = st.number_input(
                    "Length (cm)",
                    min_value=0.0,
                    max_value=5000.0,
                    value=length,
                    step=0.1,
                    format="%.1f",
                    key=f"section_length_{i}",
                    label_visibility="collapsed"
                )
                st.session_state.section_lengths[i] = new_length
            
            with col3:
                # Calculate cumulative lengths
                top_cum = total_length
                bottom_cum = top_cum + new_length  # <-- Add this line!
                st.write(f"{top_cum:.1f} - {bottom_cum:.1f}")
                total_length = bottom_cum
                
                # Store for saving
                sections_data.append({
                    "section_number": i + 1,
                    "length": new_length,
                    "top_cum": top_cum,
                    "bottom_cum": bottom_cum
                })
            
            with col4:
                # Insert button - adds a new section after this one
                if st.button("➕", key=f"insert_{i}", help=f"Insert section after {i+1}"):
                    st.session_state.section_lengths.insert(i + 1, 50.0)  # Default 50cm
                    st.rerun()
            
            with col5:
                # Delete button - removes this section
                if len(st.session_state.section_lengths) > 1:  # Don't allow deleting the last section
                    if st.button("❌", key=f"delete_{i}", help=f"Delete section {i+1}"):
                        st.session_state.section_lengths.pop(i)
                        st.rerun()
        
        # Add section at the end
        st.markdown("---")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("**Add new section at the end:**")
        with col2:
            if st.button("➕ Add Section", key="add_end"):
                st.session_state.section_lengths.append(50.0)  # Default 50cm
                st.rerun()
        
        # Summary
        st.markdown("---")
        st.subheader("Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Sections", len(st.session_state.section_lengths))
        with col2:
            st.metric("Total Core Length", f"{total_length:.1f} cm")
        with col3:
            # Count how many sections have length > 0
            active_sections = sum(1 for length in st.session_state.section_lengths if length > 0)
            st.metric("Active Sections", active_sections)
        
        # Preview table
        if sections_data:
            st.write("**Preview:**")
            preview_df = pd.DataFrame([
                {
                    "Section": data["section_number"],
                    "Length (cm)": f"{data['length']:.1f}",
                    "Top Cumulative (cm)": f"{data['top_cum']:.1f}",
                    "Bottom Cumulative (cm)": f"{data['bottom_cum']:.1f}"
                }
                for data in sections_data if data["length"] > 0
            ])
            st.dataframe(preview_df, use_container_width=True)
        
        # Save button
        if st.button("💾 Save All Changes", type="primary"):
            try:
                # Fetch existing sections from DB (with IDs)
                db_sections = get_sections_for_core(selected_core_id)
                db_section_ids = [s[0] for s in db_sections]

                # Prepare new sections data (only those with length > 0)
                new_sections = [
                    {
                        "section_number": i + 1,
                        "length": length,
                        "top_cum": sum(st.session_state.section_lengths[:i]),
                        "bottom_cum": sum(st.session_state.section_lengths[:i+1])
                    }
                    for i, length in enumerate(st.session_state.section_lengths)
                    if length > 0
                ]

                # Update or insert sections
                for i, section in enumerate(new_sections):
                    if i < len(db_sections):
                        # Update existing section
                        section_id = db_sections[i][0]
                        update_section(
                            section_id,
                            section["length"],
                            section["top_cum"],
                            section["bottom_cum"]
                        )
                    else:
                        # Insert new section
                        insert_section(
                            selected_core_id,
                            section["section_number"],
                            section["length"],
                            section["top_cum"],
                            section["bottom_cum"]
                        )

                # Delete extra sections if any
                if len(db_sections) > len(new_sections):
                    for j in range(len(new_sections), len(db_sections)):
                        section_id = db_sections[j][0]
                        try:
                            delete_section(section_id)
                        except psycopg2.errors.ForeignKeyViolation:
                            st.error(
                                "❌ Cannot delete section because it is referenced by other data (e.g., CT scan data). "
                                "Please remove related data first."
                            )
                            raise

                st.success("✅ Section records updated successfully!")
                st.write(f"**Sections saved:** {len(new_sections)}")
                st.write(f"**Total core length:** {sum([s['length'] for s in new_sections]):.1f} cm")

            except psycopg2.errors.ForeignKeyViolation:
                st.error(
                    "❌ Cannot delete section because it is referenced by other data (e.g., CT scan data). "
                    "Please remove related data first."
                )
            except Exception as e:
                st.error(f"Error saving sections: {e}")

# Instructions
st.markdown("---")
st.markdown("""
### Instructions:
1. **Edit lengths** directly in the input fields
2. **Insert sections** using ➕ buttons (adds after that section)
3. **Delete sections** using ❌ buttons 
4. **Add sections at end** using the "Add Section" button
5. **Save changes** to update the database

**Notes:**
- Section numbers automatically renumber (1, 2, 3, ...)
- Cumulative lengths are calculated automatically
- Only sections with length > 0 are saved
- Insert/delete operations renumber all subsequent sections
""")
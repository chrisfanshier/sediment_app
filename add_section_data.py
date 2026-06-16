import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores, get_existing_sections, insert_section, add_sync_tracking
from sqlalchemy import text

st.title("📏 Add Section Data")

# Main interface
# ...existing code...
cores = fetch_cores(only_created_on_ship=True)
cores = cores[cores['core_dredge'] == 'core']
if cores.empty:
    st.warning("No cores found. Please add cores first.")
else:
    # Step 1: Select Core
    st.subheader("Select Core")
    # Use cruise_name instead of cruise
    core_options = {f"{name} ({cruise_name})": (id, name, cruise_name) for id, name, cruise_name in zip(cores['core_id'], cores['core_name'], cores['cruise_name'])}
    selected_core_label = st.selectbox("Select Core", [""] + list(core_options.keys()))
    
    if selected_core_label:
        selected_core_id, selected_core_name, selected_cruise_name = core_options[selected_core_label]
        
        # Check for existing sections
        existing_sections = get_existing_sections(selected_core_id)
        
        if existing_sections and all(len(section) >= 4 for section in existing_sections):
            st.info(f"**Existing sections for {selected_core_name}:**")
            for section in existing_sections:
                st.write(f"Section {section[0]}: Length {section[1]} cm (Cumulative: {section[2]} - {section[3]} cm)")
            st.warning("This core already has sections. Use the Edit Section Data page to modify existing sections.")
        elif existing_sections:
            st.warning("This core already has section data. Use the Edit Section Data page to make changes.")
        else:
            # Step 2: Number of sections
            st.subheader("Section Configuration")
            num_sections = st.number_input("Number of Sections", min_value=1, max_value=20, value=1, step=1)
            
            if num_sections > 0:
                st.subheader("Section Lengths")
                st.write("Enter the length of each section in centimeters. Cumulative lengths will be calculated automatically.")
                
                # Initialize section lengths in session state if not exists
                if "section_lengths" not in st.session_state:
                    st.session_state.section_lengths = {}
                
                # Create input fields for each section
                section_lengths = {}
                section_splits = {}
                total_length = 0
                
                for i in range(1, num_sections + 1):
                    col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
                    
                    with col1:
                        st.write(f"**Section {i}:**")
                    
                    with col2:
                        length_key = f"section_{i}_length"
                        section_length = st.number_input(
                            f"Length (cm)", 
                            min_value=0.0, 
                            max_value=5000.0,  # Changed from 1000.0 to 5000.0
                            value=0.0,
                            step=0.1,
                            format="%.1f",
                            key=length_key
                        )
                        section_lengths[i] = section_length
                        
                    with col3:
                        # Calculate cumulative lengths
                        top_cum_length = total_length
                        bottom_cum_length = total_length + section_length
                        st.write(f"Cumulative: {top_cum_length:.1f} - {bottom_cum_length:.1f} cm")
                        
                        # Update total for next section
                        total_length = bottom_cum_length

                    with col4:
                        split_key = f"section_{i}_split"
                        section_splits[i] = st.checkbox("Split?", key=split_key)
                
                # Show summary
                if any(length > 0 for length in section_lengths.values()):
                    st.subheader("Summary")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Sections", num_sections)
                    with col2:
                        st.metric("Total Core Length", f"{total_length:.1f} cm")
                    
                    # Preview table
                    preview_data = []
                    cumulative = 0
                    for i in range(1, num_sections + 1):
                        length = section_lengths[i]
                        if length > 0:  # Only show sections with length > 0
                            top = cumulative
                            bottom = cumulative + length
                            preview_data.append({
                                "Section": i,
                                "Length (cm)": f"{length:.1f}",
                                "Split": section_splits[i],
                                "Top Cumulative (cm)": f"{top:.1f}",
                                "Bottom Cumulative (cm)": f"{bottom:.1f}"
                            })
                            cumulative = bottom
                    
                    if preview_data:
                        st.write("**Preview:**")
                        st.dataframe(pd.DataFrame(preview_data), use_container_width=True)
                        
                        # Save button
                        if st.button("Save Sections", type="primary"):
                            try:
                                cumulative = 0
                                sections_created = 0
                                
                                with get_connection() as conn:
                                    for i in range(1, num_sections + 1):
                                        length = section_lengths[i]
                                        if length > 0:  # Only save sections with length > 0
                                            top_cum = cumulative
                                            bottom_cum = cumulative + length
                                            
                                            values = {
                                                'core_id': selected_core_id,
                                                'section_number': i,
                                                'section_length': length,
                                                'split': section_splits[i],
                                                'top_cum_length': top_cum,
                                                'bottom_cum_length': bottom_cum
                                            }
                                            
                                            # Add sync tracking
                                            values = add_sync_tracking(values)
                                            
                                            query = text("""
                                                INSERT INTO sections (
                                                    core_id, section_number, section_length, split,
                                                    top_cum_length, bottom_cum_length,
                                                    created_on_ship, sync_status
                                                ) VALUES (
                                                    :core_id, :section_number, :section_length, :split,
                                                    :top_cum_length, :bottom_cum_length,
                                                    :created_on_ship, :sync_status
                                                )
                                            """)
                                            
                                            conn.execute(query, values)
                                            
                                            cumulative = bottom_cum
                                            sections_created += 1
                                    
                                    conn.commit()
                                
                                st.success(f"Successfully created {sections_created} sections for core {selected_core_name}!")
                                st.write(f"**Total core length:** {cumulative:.1f} cm")
                                
                                # Clear session state
                                if "section_lengths" in st.session_state:
                                    del st.session_state.section_lengths
                                
                                # Offer to continue
                                if st.button("Add sections to another core"):
                                    st.rerun()
                                    
                            except Exception as e:
                                st.error(f"Error saving sections: {e}")
                    else:
                        st.info("Enter section lengths greater than 0 to create sections.")

# Instructions
st.markdown("---")
st.markdown("""
### Instructions:
1. **Select a core** from the dropdown
2. **Enter the number of sections** the core will be divided into
3. **Enter the length** of each section in centimeters
4. **Review the preview** showing cumulative lengths
5. **Save** to create the section records

**Note:** 
- Section 1 starts at the top of the core (cumulative length 0)
- Cumulative lengths are calculated automatically
- Only sections with length > 0 will be saved
- Each core can only have sections added once (use Edit Section Data to modify)
""")
import streamlit as st
import pandas as pd
from db_util import get_connection  

def view_cores():
    st.title("📊 View and Explore Cores Data")

    # Fetch the cores table from the database
    with get_connection() as conn:
        query_cores = "SELECT * FROM cores ORDER BY core_name"
        cores_data = pd.read_sql(query_cores, conn)

        # Fetch vessel names
        query_vessels = "SELECT vessel_id, vessel_name FROM vessels"
        vessels_df = pd.read_sql(query_vessels, conn)
        vessel_map = vessels_df.set_index('vessel_id')['vessel_name'].to_dict()

        # Fetch core type names
        query_core_types = "SELECT core_type_id, core_type_name FROM core_types"
        core_types_df = pd.read_sql(query_core_types, conn)
        core_type_map = core_types_df.set_index('core_type_id')['core_type_name'].to_dict()

        # Fetch file counts for each core
        query_files = """
            SELECT core_id, file_type, COUNT(*) AS file_count
            FROM files
            GROUP BY core_id, file_type
        """
        files_data = pd.read_sql(query_files, conn)

        # Create columns for sensor data and MSCL data
        sensor_data_map = files_data[files_data['file_type'] == 'RBR Sensor'].set_index('core_id')['file_count'].to_dict()
        mscl_data_map = files_data[files_data['file_type'] == 'MSCL Data'].set_index('core_id')['file_count'].to_dict()

        cores_data['has_sensor_data'] = cores_data['core_id'].map(lambda x: sensor_data_map.get(x, 0) > 0)
        cores_data['has_mscl_data'] = cores_data['core_id'].map(lambda x: mscl_data_map.get(x, 0) > 0)

        # Replace IDs with names
        cores_data['vessel_name'] = cores_data['vessel_id'].map(vessel_map).fillna(cores_data['vessel_id'])
        cores_data['core_type_name'] = cores_data['core_type_id'].map(core_type_map).fillna(cores_data['core_type_id'])

        # Drop the original ID columns if you only want to display names
        if 'vessel_id' in cores_data.columns:
            cores_data.drop(columns=['vessel_id'], inplace=True)
        if 'core_type_id' in cores_data.columns:
            cores_data.drop(columns=['core_type_id'], inplace=True)

    if not cores_data.empty:
        # Sidebar Search Boxes (Above Column Selection)
        st.sidebar.header("Search")
        search_cruise = st.sidebar.text_input("Search Cruise:", value="")
        search_core_name = st.sidebar.text_input("Search Core Name:", value="")

        # Sidebar: Column visibility toggle
        st.sidebar.header("Column Visibility")
        all_columns = list(cores_data.columns)  # Get all column names
        visible_columns = st.sidebar.multiselect(
            "Select columns to display:",
            options=all_columns,
            default=all_columns  # Default to showing all columns
        )

        # Filter the DataFrame to only show selected columns
        filtered_data = cores_data[visible_columns].copy()

        # Apply search filters
        if search_cruise:
            filtered_data = filtered_data[filtered_data['cruise'].astype(str).str.contains(search_cruise, case=False)]
        if search_core_name:
            filtered_data = filtered_data[filtered_data['core_name'].astype(str).str.contains(search_core_name, case=False)]

        # Sidebar filters for all visible columns (excluding search fields)
        st.sidebar.header("Filter Options")
        for column in visible_columns:
            if column not in ["cruise", "core_name", "vessel_name", "core_type_name"]:  # Exclude the name columns as well
                unique_values = cores_data[column].dropna().unique()

                if len(unique_values) < 20:  # Use a multiselect filter for categorical-like columns
                    selected_values = st.sidebar.multiselect(
                        f"Filter by {column}:", options=["All"] + list(unique_values), default="All"
                    )
                    if "All" not in selected_values:
                        filtered_data = filtered_data[filtered_data[column].isin(selected_values)]

        # Show the filtered table
        st.write("### Cores Table")
        st.dataframe(filtered_data, use_container_width=True)  # Display the filtered cores table

        # Add download functionality for filtered data
        st.download_button(
            label="Download Filtered Data as CSV",
            data=filtered_data.to_csv(index=False),  # Convert the filtered DataFrame to a CSV string
            file_name="filtered_cores_table.csv",
            mime="text/csv"
        )

        # Inform users about filtering and column visibility
        st.markdown(
            """
            - Use the **sidebar** to search by Cruise and Core Name, toggle column visibility, and filter the table.
            - The table updates dynamically based on your selections.
            - You can also download the filtered data using the button below.
            """
        )
    else:
        st.write("No cores added yet.")
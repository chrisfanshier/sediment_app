import streamlit as st
import pandas as pd
from db_util import get_connection

def view_sections():
    st.title("📏 View and Explore Sections Data")

    # Fetch the sections table from the database
    with get_connection() as conn:
        # Get sections data with cruise and core_name instead of IDs
        query_sections = """
        SELECT cr.cruise_name,
            c.core_name,
            s.section_number,
            s.section_length,
           
            s.bottom_cum_length
        FROM sections s
        JOIN cores c ON s.core_id = c.core_id
        JOIN cruises cr ON c.cruise_id = cr.cruise_id
        ORDER BY cr.cruise_name, c.core_name, s.section_number
        """
        sections_data = pd.read_sql(query_sections, conn)

        cruises = pd.read_sql("SELECT DISTINCT cruise_name FROM cruises ORDER BY cruise_name", conn)
        cruise_list = cruises['cruise_name'].tolist()

        # Get core_id and core_name for the selected cruise
        if cruise_list:
            selected_cruise = st.sidebar.selectbox("Select a cruise to filter cores:", options=[""] + cruise_list)
            if selected_cruise:
# ...existing code...
                query = "SELECT core_id, core_name FROM cores WHERE cruise_name = :cruise_name ORDER BY core_name"
                cores = pd.read_sql(query, conn, params={"cruise_name": selected_cruise})
# ...existing code...
                core_list = cores[['core_id', 'core_name']].values.tolist()
            else:
                core_list = []
        else:
            selected_cruise = ""
            core_list = []

    if not sections_data.empty:
        # Sidebar Search Boxes (Above Column Selection)
        st.sidebar.header("Search")
        search_cruise = st.sidebar.text_input("Search Cruise:", value="")
        search_core_name = st.sidebar.text_input("Search Core Name:", value="")
        search_section = st.sidebar.text_input("Search Section:", value="")

        # Sidebar: Column visibility toggle
        st.sidebar.header("Column Visibility")
        all_columns = list(sections_data.columns)  # Get all column names
        visible_columns = st.sidebar.multiselect(
            "Select columns to display:",
            options=all_columns,
            default=all_columns  # Default to showing all columns
        )

        # Filter the DataFrame to only show selected columns
        filtered_data = sections_data[visible_columns].copy()

        # Apply search filters
        if search_cruise:
            filtered_data = filtered_data[filtered_data['cruise_name'].astype(str).str.contains(search_cruise, case=False)]
        if search_core_name:
            filtered_data = filtered_data[filtered_data['core_name'].astype(str).str.contains(search_core_name, case=False)]
        if search_section:
            # Search in section_number
            section_filter = (
                filtered_data['section_number'].astype(str).str.contains(search_section, case=False, na=False)
            )
            filtered_data = filtered_data[section_filter]

        # Sidebar filters for all visible columns (excluding search fields)
        st.sidebar.header("Filter Options")
        for column in visible_columns:
            if column not in ["cruise", "core_name"]:  # Exclude the search columns
                unique_values = sections_data[column].dropna().unique()

                if len(unique_values) < 20:  # Use a multiselect filter for categorical-like columns
                    selected_values = st.sidebar.multiselect(
                        f"Filter by {column}:", options=["All"] + list(unique_values), default="All"
                    )
                    if "All" not in selected_values:
                        filtered_data = filtered_data[filtered_data[column].isin(selected_values)]

        # Show the filtered table
        st.write("### Sections Table")
        st.dataframe(filtered_data, use_container_width=True)  # Display the filtered sections table

        # Add download functionality for filtered data
        st.download_button(
            label="Download Filtered Data as CSV",
            data=filtered_data.to_csv(index=False),  # Convert the filtered DataFrame to a CSV string
            file_name="filtered_sections_table.csv",
            mime="text/csv"
        )

        # Inform users about filtering and column visibility
        st.markdown(
            """
            - Use the **sidebar** to search by Cruise, Core Name, and Section, toggle column visibility, and filter the table.
            - The table updates dynamically based on your selections.
            - You can also download the filtered data using the button below.
            """
        )
    else:
        st.info("No sections data found. Please check the database or adjust your filters.")
        st.write("No sections found in the database.")
        st.info("Sections are created when you add CT scan data. Go to 'Add CT Data' to create sections.")

if __name__ == "__main__":
    view_sections()
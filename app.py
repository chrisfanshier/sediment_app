import streamlit as st
from view_cores import view_cores
from view_mscl import visualize_mscl_data
from view_sensor import view_sensor_data  
from view_sections import view_sections
from view_cruises import view_cruises
from multiplot_st import multiplot_sensor_data  # Add this import

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
    /* Reduce padding in the main content container */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0rem !important; /* Remove left padding */
        padding-right: 1rem !important;
    }
    /* Remove margin between the sidebar and main content */
    .css-1lcbmhc {
        margin-left: 0rem !important; /* Remove left margin */
        margin-right: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Sidebar navigation
menu = ["View Cruises", "View Cores", "View Sections", "Visualize MSCL Data", "View Sensor Data", "Sensor Plotter"]  # Add to menu
choice = st.sidebar.radio("Select Option", menu)

# Render the selected page
if choice == "View Cruises":
    view_cruises()
elif choice == "View Cores":
    view_cores()
elif choice == "Visualize MSCL Data":
    visualize_mscl_data()
elif choice == "View Sensor Data":  
    view_sensor_data()
elif choice == "View Sections":
    view_sections()
elif choice == "Sensor Plotter":
    multiplot_sensor_data()  # Add this
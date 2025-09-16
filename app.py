import streamlit as st
from view_cores import view_cores

# Sidebar navigation
menu = ["View Cores"]
choice = st.sidebar.radio("Select Option", menu)

# Render the selected page
if choice == "View Cores":
    view_cores()
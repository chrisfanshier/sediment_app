import streamlit as st

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

# Sidebar navigation
menu = ["Add Core Data", "Edit Core Data"]
choice = st.sidebar.radio("Select Option", menu)

# Render the selected page
if choice == "Add Core Data":
    # Execute the add_core_data.py file content
    with open("add_core_data.py", "r", encoding="utf-8") as f:  # Add encoding="utf-8"
        add_core_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_core_code = add_core_code.replace('st.set_page_config(layout="wide")', '')
    add_core_code = add_core_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_core_code)

elif choice == "Edit Core Data":
    # Execute the edit_core_data.py file content
    with open("edit_core_data.py", "r", encoding="utf-8") as f:  # Add encoding="utf-8"
        edit_core_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_core_code = edit_core_code.replace('st.set_page_config(layout="wide")', '')
    edit_core_code = edit_core_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_core_code)
import streamlit as st

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

# Sidebar navigation - add the new cruise edit option
menu = ["Add Cruise Data", "Edit Cruise Data", "Add Core Data", "Edit Core Data", "Add Section Data", "Edit Section Data", "Add Dredge Data", "Edit Dredge Data"]
choice = st.sidebar.radio("Select Option", menu)

# Render the selected page
if choice == "Add Cruise Data":
    # Execute the add_cruise_data.py file content
    with open("add_cruise_data.py", "r", encoding="utf-8") as f:
        add_cruise_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_cruise_code = add_cruise_code.replace('st.set_page_config(layout="wide")', '')
    add_cruise_code = add_cruise_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_cruise_code)

elif choice == "Edit Cruise Data":
    # Execute the edit_cruise_data.py file content
    with open("edit_cruise_data.py", "r", encoding="utf-8") as f:
        edit_cruise_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_cruise_code = edit_cruise_code.replace('st.set_page_config(layout="wide")', '')
    edit_cruise_code = edit_cruise_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_cruise_code)

elif choice == "Add Core Data":
    # Execute the add_core_data.py file content
    with open("add_core_data.py", "r", encoding="utf-8") as f:
        add_core_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_core_code = add_core_code.replace('st.set_page_config(layout="wide")', '')
    add_core_code = add_core_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_core_code)

elif choice == "Edit Core Data":
    # Execute the edit_core_data.py file content
    with open("edit_core_data.py", "r", encoding="utf-8") as f:
        edit_core_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_core_code = edit_core_code.replace('st.set_page_config(layout="wide")', '')
    edit_core_code = edit_core_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_core_code)

elif choice == "Add Section Data":
    # Execute the add_section_data.py file content
    with open("add_section_data.py", "r", encoding="utf-8") as f:
        add_section_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_section_code = add_section_code.replace('st.set_page_config(layout="wide")', '')
    add_section_code = add_section_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_section_code)

elif choice == "Edit Section Data":
    # Execute the edit_section_data.py file content
    with open("edit_section_data.py", "r", encoding="utf-8") as f:
        edit_section_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_section_code = edit_section_code.replace('st.set_page_config(layout="wide")', '')
    edit_section_code = edit_section_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_section_code)

elif choice == "Add Dredge Data":
    # Execute the add_dredge_data.py file content
    with open("add_dredge_data.py", "r", encoding="utf-8") as f:
        add_dredge_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_dredge_code = add_dredge_code.replace('st.set_page_config(layout="wide")', '')
    add_dredge_code = add_dredge_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_dredge_code)

elif choice == "Edit Dredge Data":
    # Execute the edit_dredge_data.py file content
    with open("edit_dredge_data.py", "r", encoding="utf-8") as f:
        edit_dredge_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_dredge_code = edit_dredge_code.replace('st.set_page_config(layout="wide")', '')
    edit_dredge_code = edit_dredge_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_dredge_code)
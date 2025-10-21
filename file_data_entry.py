import streamlit as st

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

# Sidebar navigation
menu = ["Add Data File", "Edit Data File", "Add Winch Data", "Edit Winch Data"]
choice = st.sidebar.radio("Select Option", menu)

# Render the selected page
if choice == "Add Data File":
    # Execute the add_data_file.py file content
    with open("add_data_file.py", "r", encoding="utf-8") as f:
        add_file_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_file_code = add_file_code.replace('st.set_page_config(layout="wide")', '')
    add_file_code = add_file_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(add_file_code)

elif choice == "Edit Data File":
    # Execute the edit_data_file.py file content
    with open("edit_data_file.py", "r", encoding="utf-8") as f:
        edit_file_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_file_code = edit_file_code.replace('st.set_page_config(layout="wide")', '')
    edit_file_code = edit_file_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_file_code)

elif choice == "Add Winch Data":
    # Execute the add_winch_data.py file content
    with open("add_winch_data.py", "r", encoding="utf-8") as f:
        add_winch_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    add_winch_code = add_winch_code.replace('st.set_page_config(layout="wide")', '')
    add_winch_code = add_winch_code.replace("st.set_page_config(layout='wide')", '')
    add_winch_code = add_winch_code.replace('st.set_page_config(page_title="Add Winch Data", layout="wide")', '')
    add_winch_code = add_winch_code.replace("st.set_page_config(page_title='Add Winch Data', layout='wide')", '')
    
    exec(add_winch_code)

elif choice == "Edit Winch Data":
    # Execute the edit_winch_data.py file content
    with open("edit_winch_data.py", "r", encoding="utf-8") as f:
        edit_winch_code = f.read()
    
    # Remove any st.set_page_config lines to avoid conflicts
    edit_winch_code = edit_winch_code.replace('st.set_page_config(layout="wide")', '')
    edit_winch_code = edit_winch_code.replace("st.set_page_config(layout='wide')", '')
    
    exec(edit_winch_code)
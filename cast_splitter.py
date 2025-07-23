
import pandas as pd
import streamlit as st

st.title("Cast Data Splitter for .txt Files")

st.set_option('server.maxUploadSize', 1000)

# File uploader
uploaded_file = st.file_uploader("Upload your .txt file", type=["txt"])

if uploaded_file is not None:
    try:
        # Attempt to load the file as a tabular dataset
        # Adjust the delimiter as needed (e.g., '\t' for tab-separated, ',' for comma-separated)
        data = pd.read_csv(uploaded_file, delimiter='\t')  # Change delimiter if necessary
        st.success("File loaded successfully!")

        # Display the first few rows of the data
        st.subheader("Preview of Uploaded Data")
        st.dataframe(data.head())

        # Split into casts
        def split_into_casts(data, depth_column='Depth', surface_threshold=5):
            """
            Split the data into casts based on the depth.
            A cast starts when the depth exceeds the surface threshold
            and ends when it drops below the surface threshold.
            """
            casts = []
            current_cast = []
            in_cast = False

            for i in range(len(data)):
                curr_depth = data[depth_column].iloc[i]

                # Check if we are in the "surface" zone
                if curr_depth < surface_threshold:
                    if in_cast:
                        # End the current cast when back at surface
                        casts.append(pd.DataFrame(current_cast))
                        current_cast = []
                        in_cast = False
                else:
                    # Start a new cast if we are not already in one
                    if not in_cast:
                        in_cast = True
                    current_cast.append(data.iloc[i])

            # Add the last cast if it has data
            if current_cast:
                casts.append(pd.DataFrame(current_cast))

            return casts

        # Process the data to split into casts
        casts = split_into_casts(data)

        # Display results
        st.subheader("Identified Casts")
        for i, cast in enumerate(casts):
            st.write(f"Cast {i + 1} has {len(cast)} rows.")
            st.dataframe(cast)

        st.success(f"Successfully identified {len(casts)} casts!")

    except Exception as e:
        st.error(f"An error occurred while processing the file: {e}")
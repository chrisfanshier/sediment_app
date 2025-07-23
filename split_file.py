import streamlit as st
import pandas as pd
import os
from io import BytesIO

st.title("Split CSV with Casts into Separate Files")

uploaded_csv = st.file_uploader("Upload the CSV file with the 'cast' column", type=["csv"])
output_directory = st.text_input("Enter the directory to save the separate cast files:", "separated_casts_csv")

if uploaded_csv is not None and output_directory:
    try:
        df = pd.read_csv(uploaded_csv)
        st.subheader("Preview of Uploaded Data")
        st.dataframe(df.head())

        if 'cast' in df.columns:
            unique_casts = df['cast'].unique()
            unique_casts = [cast for cast in unique_casts if pd.notna(cast) and cast != 0] # Exclude NaN and 0

            if unique_casts:
                st.subheader("Identified Cast Numbers")
                st.write(unique_casts)

                if not os.path.exists(output_directory):
                    os.makedirs(output_directory)
                    st.info(f"Created output directory: {output_directory}")

                for cast_number in unique_casts:
                    cast_df = df[df['cast'] == cast_number].drop(columns=['cast'])
                    output_filename = os.path.join(output_directory, f"cast_{int(cast_number)}.csv")
                    cast_df.to_csv(output_filename, index=False)
                    st.success(f"Cast {int(cast_number)} saved to: {output_filename}")

                st.info(f"All casts saved to the '{output_directory}' directory.")

            else:
                st.info("No casts found in the 'cast' column (excluding NaN and 0).")

        else:
            st.error("Error: The uploaded CSV file does not contain a 'cast' column.")

    except Exception as e:
        st.error(f"An error occurred: {e}")
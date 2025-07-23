import streamlit as st
from pyrsktools import RSK
import pandas as pd
import os
from io import BytesIO

st.title("RSK File - Identify Casts and Export to CSV")

def process_rsk_data(file_path):
    """Process the RSK file and return the RSK object."""
    from pyrsktools import RSK
    try:
        rsk = RSK(file_path)
        rsk.open()
        rsk.readdata()
        rsk.deriveseapressure()  # Calculate sea pressure
        rsk.derivedepth(latitude=45.0)  # Calculate depth
        return rsk
    except FileNotFoundError:
        st.error(f"Error: RSK file not found at path: {file_path}")
        return None
    except Exception as e:
        st.error(f"Error processing RSK file at {file_path}: {e}")
        return None

uploaded_file = st.file_uploader("Upload a single RSK file", type=["rsk"])

if uploaded_file is not None:
    # Save the uploaded file temporarily
    with open("temp.rsk", "wb") as f:
        f.write(uploaded_file.getbuffer())

    file_path = "temp.rsk"
    rsk_original = process_rsk_data(file_path)

    if rsk_original is not None:
        df_full = pd.DataFrame(rsk_original.data).copy() # Create DataFrame
        st.subheader("Preview of Data (Full Resolution)")
        st.dataframe(df_full.head())

        # Downsample for cast detection
        downsampled_df = df_full.iloc[::100].copy()
        downsampled_df['original_index'] = df_full.index[::100]

        casts_indices = []
        in_cast = False
        cast_number = 0
        cast_start_original_index = None

        for index_downsampled, row in downsampled_df.iterrows():
            depth = row['depth']
            original_index = row['original_index']

            if not in_cast and depth > 5:
                in_cast = True
                cast_number += 1
                cast_start_original_index = original_index
            elif in_cast and depth < 5:
                in_cast = False
                if cast_start_original_index is not None:
                    casts_indices.append({"cast_number": cast_number, "start": cast_start_original_index, "end": original_index})
                    cast_start_original_index = None

        if casts_indices:
            cast_summary = pd.DataFrame(casts_indices)
            st.subheader("Identified Casts (Based on Downsampled Data - Original Indices)")
            st.dataframe(cast_summary)

            # Assign cast numbers to the full DataFrame
            df_full['cast'] = 0  # Initialize cast column
            for cast_info in casts_indices:
                cast_number = cast_info['cast_number']
                start_index = cast_info['start']
                end_index = cast_info['end']
                df_full.loc[start_index:end_index, 'cast'] = cast_number

            st.subheader("Full Data with Cast Information")
            st.dataframe(df_full.head())

            # Offer CSV download
            csv_buffer = BytesIO()
            df_full.to_csv(csv_buffer, index=False)
            st.download_button(
                label="Download Data with Casts as CSV",
                data=csv_buffer.getvalue(),
                file_name=f"{os.path.splitext(os.path.basename(file_path))[0]}_with_casts.csv",
                mime="text/csv",
            )

        else:
            st.info("No casts found based on the defined criteria in the downsampled data.")

        # Ensure the RSK object is closed
        if hasattr(rsk_original, 'close') and callable(rsk_original.close):
            rsk_original.close()
            st.info("Original RSK file object closed.")

    # Clean up the temporary file
    if uploaded_file is not None and os.path.exists("temp.rsk"):
        os.remove("temp.rsk")
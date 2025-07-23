import os
import streamlit as st
from pyrsktools import RSK
import pandas as pd

# Streamlit App
st.title("Extract Max Depth, Launch Time, and Recovery Time from RSK Files")

# Directory Selection
directory = st.text_input("Enter the directory containing RSK files:")

if directory:
    if not os.path.isdir(directory):
        st.error("The specified path is not a valid directory.")
    else:
        # Identify all .rsk files in the directory
        rsk_files = [f for f in os.listdir(directory) if f.endswith(".rsk")]
        
        if not rsk_files:
            st.warning("No .rsk files found in the specified directory.")
        else:
            # Initialize results
            results = []

            # Process each file
            for filename in rsk_files:
                file_path = os.path.join(directory, filename)
                try:
                    # Open the RSK file
                    with RSK(file_path) as rsk:
                        rsk.open()
                        rsk.readdata()  # Read the raw data

                        # Step 1: Calculate sea pressure
                        st.write(f"Processing {filename}: Calculating Sea Pressure...")
                        try:
                            rsk.deriveseapressure()  # Default atmospheric pressure
                            st.write(f"Sea pressure calculated successfully for {filename}.")
                        except Exception as e:
                            st.warning(f"Could not calculate sea pressure for {filename}: {e}")
                            continue

                        # Step 2: Calculate depth
                        st.write(f"Processing {filename}: Calculating Depth...")
                        try:
                            rsk.derivedepth()  # Default latitude = 45.0
                            st.write(f"Depth calculated successfully for {filename}.")
                        except Exception as e:
                            st.warning(f"Could not calculate depth for {filename}: {e}")
                            continue

                        # Extract timestamps for launch, recovery, and max depth
                        data = rsk.data
                        depth = data["depth"]
                        timestamps = data["timestamp"]

                        # Launch time: First timestamp where depth exceeds 2
                        launch_time = timestamps[depth > 2][0] if any(depth > 2) else None

                        # Recovery time: First timestamp after launch where depth falls below 2
                        recover_time = None
                        if launch_time is not None:
                            recover_time = timestamps[(depth < 2) & (timestamps > launch_time)][0] if any((depth < 2) & (timestamps > launch_time)) else None

                        # Max depth timestamp
                        max_depth_index = depth.argmax()
                        max_depth_timestamp = timestamps[max_depth_index]

                        # Append result
                        results.append({
                            "Filename": filename,
                            "Max Depth Timestamp": max_depth_timestamp,
                            "Launch Time": launch_time,
                            "Recover Time": recover_time
                        })

                except Exception as e:
                    st.warning(f"Could not process {filename}: {e}")

            # Display results in a table
            if results:
                df = pd.DataFrame(results)
                st.subheader("Results")
                st.dataframe(df)
            else:
                st.warning("No valid data could be extracted from the RSK files.")
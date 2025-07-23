import streamlit as st
from pyrsktools import RSK
import pandas as pd
import os
import io
import contextlib
import plotly.express as px
import numpy as np

# Directory containing the RSK files
rsk_directory = r"C:\sediment_app\uploaded_files"

# Get a list of all .rsk files in the specified directory
rsk_files = [f for f in os.listdir(rsk_directory) if f.endswith(".rsk")]

# Streamlit App
st.title("RSK File Processor")

# File Selection Dropdown
selected_file = st.selectbox("Select an RSK file:", rsk_files)

@st.cache_data
def process_rsk_data(file_path):
    """Process the RSK file and return a DataFrame with calculated fields."""
    with RSK(file_path) as rsk:
        rsk.open()
        rsk.readdata()
        rsk.deriveseapressure()  # Calculate sea pressure
        rsk.derivedepth(latitude=45.0)  # Calculate depth

        # Convert to DataFrame
        data_dict = {
            "Timestamp": rsk.data["timestamp"],
            "Pressure (dbar)": rsk.data["pressure"],
            "Sea Pressure (dbar)": rsk.data["sea_pressure"],
            "Depth (m)": rsk.data["depth"],
        }
        df = pd.DataFrame(data_dict)
    return df


@st.cache_data
def downsample_data(df, max_points=1000):
    """Downsample the DataFrame to a maximum number of points."""
    if len(df) > max_points:
        # Use numpy to sample evenly across the dataset
        indices = np.linspace(0, len(df) - 1, max_points, dtype=int)
        return df.iloc[indices]
    return df


if selected_file:
    file_path = os.path.join(rsk_directory, selected_file)
    try:
        # Process the selected RSK file
        st.subheader(f"Processing: {selected_file}")
        df = process_rsk_data(file_path)

        st.subheader("Preview of Data")
        st.dataframe(df.head())

        # Downsample data for plotting
        st.subheader("Interactive Plotting")
        max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
        downsampled_df = downsample_data(df, max_points=max_points)

        # Dropdown for selecting a parameter to plot
        y_axis = st.selectbox(
            "Select Parameter to Plot:",
            options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
            index=2
        )

        # Plotly interactive plot with downsampled data
        fig = px.line(downsampled_df, x="Timestamp", y=y_axis, title=f"{y_axis} Over Time (Downsampled)")
        fig.update_layout(
            xaxis_title="Timestamp",
            yaxis_title=y_axis,
            template="plotly_white",
            height=600,
        )
        st.plotly_chart(fig, use_container_width=True)

        # High-Resolution View
        st.subheader("High-Resolution Zoom")
        st.markdown(
            "Zoom in on the plot above to identify the time range you're interested in, "
            "then click the button below to view all data points in the selected range."
        )

        # Allow users to enter the high-resolution range manually
        start_time = st.text_input(
            "Start Time (YYYY-MM-DD HH:MM:SS):",
            value=str(downsampled_df["Timestamp"].iloc[0])
        )
        end_time = st.text_input(
            "End Time (YYYY-MM-DD HH:MM:SS):",
            value=str(downsampled_df["Timestamp"].iloc[-1])
        )

        if st.button("Refresh High Resolution Plot"):
            try:
                # Ensure valid timestamps are entered
                start_time = pd.to_datetime(start_time)
                end_time = pd.to_datetime(end_time)

                # Filter the high-resolution data
                high_res_df = df[(df["Timestamp"] >= start_time) & (df["Timestamp"] <= end_time)]

                if high_res_df.empty:
                    st.warning("No data points found in the selected range.")
                else:
                    # Plot high-resolution data
                    high_res_fig = px.line(
                        high_res_df, x="Timestamp", y=y_axis,
                        title=f"{y_axis} Over Time (High Resolution)"
                    )
                    high_res_fig.update_layout(
                        xaxis_title="Timestamp",
                        yaxis_title=y_axis,
                        template="plotly_white",
                        height=600,
                    )
                    st.plotly_chart(high_res_fig, use_container_width=True)
            except Exception as e:
                st.error(f"An error occurred while generating the high-resolution plot: {e}")

    except Exception as e:
        st.error(f"An error occurred while processing the RSK file: {e}")
import streamlit as st
from pyrsktools import RSK
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import datetime

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

def plot_iterative(file_path, file_name):
    """Iterative plotting based on user-selected parameters."""
    # Process the RSK file
    df = process_rsk_data(file_path)

    st.title(f"Iterative Plotting for {file_name}")

    st.subheader("Select Plotting Range and Downscaling Level")

    # Convert timestamps to Python datetime objects for sliders
    min_time = df["Timestamp"].iloc[0].to_pydatetime()
    max_time = df["Timestamp"].iloc[-1].to_pydatetime()

    # Time range sliders
    start_time = st.slider(
        "Start Time",
        min_value=min_time,
        max_value=max_time,
        value=min_time,
        format="YYYY-MM-DD HH:mm:ss"
    )
    end_time = st.slider(
        "End Time",
        min_value=min_time,
        max_value=max_time,
        value=max_time,
        format="YYYY-MM-DD HH:mm:ss"
    )

    if start_time >= end_time:
        st.warning("Start time must be earlier than the end time.")
        return

    # Downscaling level slider
    max_points = st.slider(
        "Select Max Points for Downscaling",
        min_value=100,
        max_value=5000,
        value=1000,
        step=100
    )

    # Dropdown for selecting parameter to plot
    y_axis = st.selectbox(
        "Select Parameter to Plot:",
        options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
        index=2
    )

    # Filter data based on selected time range
    filtered_df = df[(df["Timestamp"] >= start_time) & (df["Timestamp"] <= end_time)]

    if filtered_df.empty:
        st.warning("No data points found in the selected range.")
        return

    # Downsample data
    downsampled_df = downsample_data(filtered_df, max_points=max_points)

    # Generate the plot
    fig = px.line(
        downsampled_df,
        x="Timestamp",
        y=y_axis,
        title=f"{y_axis} Over Time (Downsampled: {max_points} Points)"
    )
    fig.update_layout(
        xaxis_title="Timestamp",
        yaxis_title=y_axis,
        template="plotly_white",
        height=600,
    )

    # Display the plot
    st.plotly_chart(fig, use_container_width=True)

    # Info message for iterative refinement
    st.info("Adjust the sliders above to refine the range and downscaling level, then re-plot.")
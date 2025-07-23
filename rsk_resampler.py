import streamlit as st
from pyrsktools import RSK
import pandas as pd
import os
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly_resampler import FigureResampler
from plotly_resampler.aggregation import MeanAggregator  # Import the MeanAggregator

# Streamlit App
st.title("RSK File Processor (Dynamic Zoom with Plotly Resampler)")

# File Upload
uploaded_file = st.file_uploader("Upload an RSK file", type=["rsk"])

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

if uploaded_file:
    # Save the uploaded file to a temporary location
    temp_file_path = "temp_rsk_file.rsk"
    with open(temp_file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    try:
        # Process the RSK file and cache the results
        st.subheader("Processing RSK File...")
        df = process_rsk_data(temp_file_path)

        st.subheader("Preview of Data")
        st.dataframe(df.head())

        # Dropdown for selecting a parameter to plot
        y_axis = st.selectbox(
            "Select Parameter to Plot:",
            options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
            index=2
        )

        # Create a FigureResampler object directly, passing an instance of the aggregator
        fig_resampler = FigureResampler(default_downsampler=MeanAggregator())

        # Add the trace to the FigureResampler
        fig_resampler.add_trace(
            go.Scattergl(name=y_axis, x=df["Timestamp"], y=df[y_axis])
        )

        fig_resampler.update_layout(
            xaxis_title="Timestamp",
            yaxis_title=y_axis,
            template="plotly_white",
            height=600,
            title=f"{y_axis} Over Time"
        )

        st.plotly_chart(fig_resampler, use_container_width=True)

    except Exception as e:
        st.error(f"An error occurred while processing the RSK file: {e}")

    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                st.warning(f"Failed to delete the temporary file: {e}")
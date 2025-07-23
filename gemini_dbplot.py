import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# --- Database Connection Details ---
DB_HOST = "localhost"
DB_NAME = "sediment_cores"
DB_USER = "postgres"
DB_PASS = "madmaxfuryroad"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

@st.cache_data(ttl=3600)
def get_rbr_core_files():
    """
    Fetches core names and their 'RBR Sensor' file paths from the database.
    Returns a dictionary where keys are core names and values are lists of file paths.
    """
    from pyrsktools import RSK
    try:
        with engine.connect() as connection:
            query = """
                SELECT c.core_name, f.file_path
                FROM cores c
                JOIN files f ON c.core_id = f.core_id
                WHERE f.file_type = 'RBR Sensor';
            """
            df = pd.read_sql(query, connection)
            core_files = df.groupby('core_name')['file_path'].apply(list).to_dict()
            return core_files
    except Exception as e:
        st.error(f"Error connecting to the database or fetching core/file data: {e}")
        return {}

@st.cache_data
def process_rsk_data(file_path):
    """Process the RSK file and return a DataFrame with calculated fields."""
    from pyrsktools import RSK
    try:
        with RSK(file_path) as rsk:
            rsk.open()
            rsk.readdata()
            rsk.deriveseapressure()  # Calculate sea pressure
            rsk.derivedepth(latitude=45.0)  # Calculate depth
            data_dict = {
                "Timestamp": rsk.data["timestamp"],
                "Pressure (dbar)": rsk.data["pressure"],
                "Sea Pressure (dbar)": rsk.data["sea_pressure"],
                "Depth (m)": rsk.data["depth"],
            }
            df = pd.DataFrame(data_dict)
            return df
    except FileNotFoundError:
        st.error(f"Error: RSK file not found at path: {file_path}")
        return None
    except Exception as e:
        st.error(f"Error processing RSK file at {file_path}: {e}")
        return None

@st.cache_data
def downsample_data(df, max_points=1000):
    """Downsample the DataFrame to a maximum number of points."""
    import numpy as np
    if df is not None and len(df) > max_points:
        indices = np.linspace(0, len(df) - 1, max_points, dtype=int)
        return df.iloc[indices]
    return df

# --- Streamlit App ---
st.title("RBR Sensor Data Plotter")

core_files_dict = get_rbr_core_files()

if core_files_dict:
    selected_core = st.selectbox("Select an RBR Sensor Core:", list(core_files_dict.keys()))

    if selected_core:
        file_paths = core_files_dict[selected_core]
        if file_paths:
            selected_file_path = st.selectbox(f"Select a file for {selected_core}:", file_paths)

            if selected_file_path:
                st.subheader(f"Processing data from: {selected_file_path}")
                st.subheader(f"Core: {selected_core}")
                df = process_rsk_data(selected_file_path)

                if df is not None:
                    st.subheader("Preview of Data")
                    st.dataframe(df.head())

                    st.subheader("Interactive Plotting")
                    max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
                    downsampled_df = downsample_data(df, max_points=max_points)

                    y_axis = st.selectbox(
                        "Select Parameter to Plot:",
                        options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
                        index=2
                    )

                    import plotly.express as px

                    if not downsampled_df.empty:
                        fig = px.line(downsampled_df, x="Timestamp", y=y_axis, title=f"{y_axis} for {selected_core} (Downsampled)")
                        fig.update_layout(
                            xaxis_title="Timestamp",
                            yaxis_title=y_axis,
                            template="plotly_white",
                            height=600,
                        )
                        st.plotly_chart(fig, use_container_width=True)

                        st.subheader("High-Resolution Zoom")
                        st.markdown(
                            "Zoom in on the plot above to identify the time range you're interested in, "
                            "then enter the start and end times below to view the high-resolution plot."
                        )

                        # Calculate default start and end times based on maximum depth
                        if not df.empty and 'Depth (m)' in df.columns and not df['Timestamp'].empty:
                            max_depth_row = df.loc[df['Depth (m)'].idxmax()]
                            max_depth_time = pd.to_datetime(max_depth_row['Timestamp'])
                            default_start_time = max_depth_time - pd.Timedelta(minutes=10)
                            default_end_time = max_depth_time + pd.Timedelta(minutes=10)
                        else:
                            default_start_time = ""
                            default_end_time = ""

                        start_time = st.text_input(
                            "Start Time (YYYY-MM-DD HH:MM:SS):",
                            value=str(default_start_time) if isinstance(default_start_time, pd.Timestamp) else ""
                        )
                        end_time = st.text_input(
                            "End Time (YYYY-MM-DD HH:MM:SS):",
                            value=str(default_end_time) if isinstance(default_end_time, pd.Timestamp) else ""
                        )

                        if st.button("Refresh High Resolution Plot"):
                            try:
                                if not df.empty:
                                    start_time = pd.to_datetime(start_time)
                                    end_time = pd.to_datetime(end_time)
                                    high_res_df = df[(df["Timestamp"] >= start_time) & (df["Timestamp"] <= end_time)]

                                    if not high_res_df.empty:
                                        high_res_fig = px.line(
                                            high_res_df, x="Timestamp", y=y_axis,
                                            title=f"{y_axis} for {selected_core} (High Resolution)"
                                        )
                                        high_res_fig.update_layout(
                                            xaxis_title="Timestamp",
                                            yaxis_title=y_axis,
                                            template="plotly_white",
                                            height=600,
                                        )
                                        st.plotly_chart(high_res_fig, use_container_width=True)
                                    else:
                                        st.warning("No data points found in the selected range.")
                                else:
                                    st.warning("No data available for the selected file to zoom.")
                            except Exception as e:
                                st.error(f"An error occurred while generating the high-resolution plot: {e}")
                    else:
                        st.warning("No data to plot for the selected file.")
            else:
                st.info(f"No 'RBR Sensor' files found for core: {selected_core}")
        else:
            st.info(f"No 'RBR Sensor' files associated with core: {selected_core}")
else:
    st.info("No 'RBR Sensor' cores found in the database.")
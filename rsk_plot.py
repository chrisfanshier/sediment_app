import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import plotly.express as px

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
    # --- Primary File Selection ---
    selected_core = st.selectbox("Select an RBR Sensor Core (Primary):", list(core_files_dict.keys()))
    primary_file_paths = core_files_dict[selected_core]
    selected_file_path = st.selectbox(f"Select a file for {selected_core} (Primary):", primary_file_paths)

    # --- Secondary File Selection ---
    st.subheader("Overlay Plot")
    overlay_option = st.radio("Select overlay data source:", ["Same Core", "Different Core", "None"])

    overlay_file_path = None  # Initialize
    if overlay_option == "Same Core":
        overlay_file_path = st.selectbox(
            f"Select a file to overlay from {selected_core}:",
            [fp for fp in primary_file_paths if fp != selected_file_path],  # Exclude primary
            index=0 if len(primary_file_paths) > 1 else None
        )
    elif overlay_option == "Different Core":
        overlay_core = st.selectbox("Select an RBR Sensor Core (Overlay):", list(core_files_dict.keys()),
                                    index=1 if len(core_files_dict) > 1 else 0)
        overlay_file_paths = core_files_dict[overlay_core]
        overlay_file_path = st.selectbox(f"Select a file for {overlay_core} (Overlay):", overlay_file_paths)

    # --- Process Data and Plot ---
    primary_df = None # initialize
    overlay_df = None # initialize

    if selected_file_path:  # Only process if a primary file is selected
        st.subheader(f"Processing data from: {selected_file_path} (Primary)")
        st.subheader(f"Core: {selected_core} (Primary)")
        primary_df = process_rsk_data(selected_file_path)



        if overlay_file_path:
            st.subheader(f"Processing data from: {overlay_file_path} (Overlay)")
            if overlay_option == "Different Core":
                overlay_core_name = overlay_core
            else:
                overlay_core_name = selected_core
            st.subheader(f"Core: {overlay_core_name} (Overlay)")
            overlay_df = process_rsk_data(overlay_file_path)

    # --- Plotting ---
    if primary_df is not None: # only plot if primary_df is not None
        st.subheader("Preview of Primary Data")
        st.dataframe(primary_df.head())

        st.subheader("Interactive Plotting")
        max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
        primary_downsampled_df = downsample_data(primary_df, max_points=max_points)

        y_axis = st.selectbox(
            "Select Parameter to Plot:",
            options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
            index=2,
        )

        fig = px.line(primary_downsampled_df, x="Timestamp", y=y_axis,
                      title=f"{y_axis} for {selected_core} (Primary) (Downsampled)",
                      color_discrete_sequence=["blue"])  # Primary in blue

        if overlay_df is not None:
            overlay_downsampled_df = downsample_data(overlay_df, max_points=max_points)
            fig.add_trace(
                px.line(overlay_downsampled_df, x="Timestamp", y=y_axis,
                        color_discrete_sequence=["red"]).data[0]  # Overlay in red
            )
            fig.update_layout(showlegend=True,
                              legend_title_text="Data Source",
                              legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
        else:
            fig.update_layout(showlegend=False)

        fig.update_layout(
            xaxis_title="Timestamp",
            yaxis_title=y_axis,
            template="plotly_white",
            yaxis=dict(autorange="reversed"),  # Invert the y-axis
            height=600,
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- High Resolution Plot ---
        st.subheader("High-Resolution Zoom")
        st.markdown(
            "Zoom in on the plot above to identify the time range you're interested in, "
            "then enter the start and end times below to view the high-resolution plot."
        )

        # Calculate default start and end times based on maximum depth of primary
        if primary_df is not None and 'Depth (m)' in primary_df.columns and not primary_df['Timestamp'].empty:
            max_depth_row = primary_df.loc[primary_df['Depth (m)'].idxmax()]
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
            value=str(default_end_time) if isinstance(default_time, pd.Timestamp) else ""
        )

        if st.button("Refresh High Resolution Plot"):
            try:
                if primary_df is not None:
                    start_time = pd.to_datetime(start_time)
                    end_time = pd.to_datetime(end_time)
                    high_res_df = primary_df[
                        (primary_df["Timestamp"] >= start_time) & (primary_df["Timestamp"] <= end_time)]

                    high_res_fig = px.line(
                        high_res_df, x="Timestamp", y=y_axis,
                        title=f"{y_axis} for {selected_core} (Primary) (High Resolution)",
                        color_discrete_sequence=["blue"]
                    )

                    if overlay_df is not None:
                        overlay_high_res_df = overlay_df[
                            (overlay_df["Timestamp"] >= start_time) & (overlay_df["Timestamp"] <= end_time)]
                        high_res_fig.add_trace(
                            px.line(overlay_high_res_df, x="Timestamp", y=y_axis,
                                    color_discrete_sequence=["red"]).data[0]
                        )
                        high_res_fig.update_layout(showlegend=True,
                                                  legend_title_text="Data Source",
                                                  legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
                    else:
                        high_res_fig.update_layout(showlegend=False)

                    high_res_fig.update_layout(
                        xaxis_title="Timestamp",
                        yaxis_title=y_axis,
                        template="plotly_white",
                        yaxis=dict(autorange="reversed"),
                        height=600,
                    )
                    st.plotly_chart(high_res_fig, use_container_width=True)
                else:
                    st.warning("No data available for the selected file to zoom.")
            except Exception as e:
                st.error(f"An error occurred while generating the high-resolution plot: {e}")
    else:
        st.info("No 'RBR Sensor' cores found in the database.")


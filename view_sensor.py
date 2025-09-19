import streamlit as st
import pandas as pd
import plotly.express as px
from db_util import get_rbr_core_files
from utils import process_rsk_data, downsample_data

def view_sensor_data():
    """Render the View Sensor Data page."""
    st.title("RBR Sensor Data Plotter")

    # Fetch core files from the database
    try:
        core_files_dict = get_rbr_core_files()
    except RuntimeError as e:
        st.error(e)
        core_files_dict = {}

    if core_files_dict:
        # --- Primary File Selection ---
        selected_core = st.selectbox("Select an RBR Sensor Core (Primary):", list(core_files_dict.keys()))
        primary_file_paths = core_files_dict[selected_core]
        selected_file_path = st.selectbox(f"Select a file for {selected_core} (Primary):", primary_file_paths)

        # --- Secondary File Selection ---
        st.subheader("Overlay Plot")
        overlay_option = st.radio("Select overlay data source:", ["Same Core", "Different Core", "None"])
        overlay_file_path = None
        overlay_core_name = None
        if overlay_option == "Same Core":
            overlay_file_path = st.selectbox(
                f"Select a file to overlay from {selected_core}:",
                [fp for fp in primary_file_paths if fp != selected_file_path],  # Exclude primary
                index=0 if len(primary_file_paths) > 1 else None
            )
            overlay_core_name = selected_core
        elif overlay_option == "Different Core":
            overlay_core = st.selectbox("Select an RBR Sensor Core (Overlay):", list(core_files_dict.keys()),
                                        index=1 if len(core_files_dict) > 1 else 0)
            overlay_file_paths = core_files_dict[overlay_core]
            overlay_file_path = st.selectbox(f"Select a file for {overlay_core} (Overlay):", overlay_file_paths)
            overlay_core_name = overlay_core

        # --- Third Trace Selection ---
        st.subheader("Add a Third Trace (Optional)")
        third_trace_option = st.radio("Add a third data source?", ["None", "Select Core and File"])
        third_file_path = None
        third_core_name = None
        if third_trace_option == "Select Core and File":
            third_core = st.selectbox(
                "Select an RBR Sensor Core (Third Trace):", 
                list(core_files_dict.keys()), 
                key="third_core_select"
            )
            third_file_paths = core_files_dict[third_core]
            third_file_path = st.selectbox(f"Select a file for {third_core} (Third Trace):", third_file_paths, key="third_file_select")
            third_core_name = third_core

        # --- Process Data and Plot ---
        if selected_file_path:
            st.subheader(f"Processing data from: {selected_file_path} (Primary)")
            st.subheader(f"Core: {selected_core} (Primary)")
            primary_df = process_rsk_data(selected_file_path)

            overlay_df = None
            if overlay_file_path:
                st.subheader(f"Processing data from: {overlay_file_path} (Overlay)")
                st.subheader(f"Core: {overlay_core_name} (Overlay)")
                overlay_df = process_rsk_data(overlay_file_path)

            third_df = None
            if third_file_path:
                st.subheader(f"Processing data from: {third_file_path} (Third Trace)")
                st.subheader(f"Core: {third_core_name} (Third Trace)")
                third_df = process_rsk_data(third_file_path)

            # --- Plotting ---
            if primary_df is not None:
                st.subheader("Preview of Primary Data")
                st.dataframe(primary_df.head())

                # --- Downsample and Plot ---
                st.subheader("Interactive Plotting")
                max_points = st.slider("Max Points for Plotting", min_value=100, max_value=5000, value=1000, step=100)
                primary_downsampled_df = downsample_data(primary_df, max_points=max_points)

                y_axis = st.selectbox(
                    "Select Parameter to Plot:",
                    options=["Pressure (dbar)", "Sea Pressure (dbar)", "Depth (m)"],
                    index=2,
                )

                fig = px.line(
                    primary_downsampled_df, x="Timestamp", y=y_axis,
                    title=f"{y_axis} for {selected_core} (Primary) (Downsampled)",
                    color_discrete_sequence=["blue"]
                )
                fig.data[0].name = f"{selected_core} (Primary)"

                if overlay_df is not None:
                    overlay_downsampled_df = downsample_data(overlay_df, max_points=max_points)
                    overlay_trace = px.line(
                        overlay_downsampled_df, x="Timestamp", y=y_axis,
                        color_discrete_sequence=["red"]
                    ).data[0]
                    overlay_trace.name = f"{overlay_core_name} (Overlay)"
                    fig.add_trace(overlay_trace)

                if third_df is not None:
                    third_downsampled_df = downsample_data(third_df, max_points=max_points)
                    third_trace = px.line(
                        third_downsampled_df, x="Timestamp", y=y_axis,
                        color_discrete_sequence=["green"]
                    ).data[0]
                    third_trace.name = f"{third_core_name} (Third Trace)"
                    fig.add_trace(third_trace)

                fig.update_layout(
                    showlegend=True,
                    legend_title_text="Data Source",
                    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                    xaxis_title="Timestamp",
                    yaxis_title=y_axis,
                    template="plotly_white",
                    yaxis=dict(autorange="reversed"),
                    height=600,
                )
                st.plotly_chart(fig, use_container_width=True)

                # --- High Resolution Plot ---
                st.subheader("High-Resolution Zoom")
                st.markdown(
                    "Zoom in on the plot above to identify the time range you're interested in, "
                    "then enter the start and end times below to view the high-resolution plot."
                )

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
                    value=str(default_end_time) if isinstance(default_end_time, pd.Timestamp) else ""
                )

                if st.button("Refresh High Resolution Plot"):
                    try:
                        if primary_df is not None:
                            start_time_dt = pd.to_datetime(start_time)
                            end_time_dt = pd.to_datetime(end_time)
                            high_res_df = primary_df[
                                (primary_df["Timestamp"] >= start_time_dt) & (primary_df["Timestamp"] <= end_time_dt)]

                            high_res_fig = px.line(
                                high_res_df, x="Timestamp", y=y_axis,
                                title=f"{y_axis} for {selected_core} (Primary) (High Resolution)",
                                color_discrete_sequence=["blue"]
                            )
                            high_res_fig.data[0].name = f"{selected_core} (Primary)"

                            if overlay_df is not None:
                                overlay_high_res_df = overlay_df[
                                    (overlay_df["Timestamp"] >= start_time_dt) & (overlay_df["Timestamp"] <= end_time_dt)]
                                overlay_high_res_trace = px.line(
                                    overlay_high_res_df, x="Timestamp", y=y_axis,
                                    color_discrete_sequence=["red"]
                                ).data[0]
                                overlay_high_res_trace.name = f"{overlay_core_name} (Overlay)"
                                high_res_fig.add_trace(overlay_high_res_trace)

                            if third_df is not None:
                                third_high_res_df = third_df[
                                    (third_df["Timestamp"] >= start_time_dt) & (third_df["Timestamp"] <= end_time_dt)]
                                third_high_res_trace = px.line(
                                    third_high_res_df, x="Timestamp", y=y_axis,
                                    color_discrete_sequence=["green"]
                                ).data[0]
                                third_high_res_trace.name = f"{third_core_name} (Third Trace)"
                                high_res_fig.add_trace(third_high_res_trace)

                            high_res_fig.update_layout(
                                showlegend=True,
                                legend_title_text="Data Source",
                                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
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
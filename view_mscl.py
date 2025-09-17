import os
import streamlit as st
import pandas as pd
from db_util import get_connection, fetch_cores
from plotting import plot_mscl_data, plot_mscl_data_compare
from utils import parse_mscl_out_file

# --- Visualize MSCL Data Page ---
def visualize_mscl_data():
    st.title("📊 Visualize MSCL Data")
    if 'compare_enabled' not in st.session_state:
        st.session_state['compare_enabled'] = False
    if 'comparison_settings_expanded' not in st.session_state:
        st.session_state['comparison_settings_expanded'] = False

    # Fetch list of cores
    cores = fetch_cores()
    core_options = {f"{name} (ID: {id})": id for id, name in zip(cores['core_id'], cores['core_name'])}

    col1, col2 = st.columns([1, 3])

    with col1:
        st.header("Controls")
        with st.expander("Core and File Selection", expanded=True):
            selected_core_label = st.selectbox("Select Core to Visualize MSCL Data", list(core_options.keys()))
            selected_core_id = core_options[selected_core_label]

            # Fetch associated MSCL files for the selected core
            with get_connection() as conn:
                query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))

            if not df_files.empty:
                selected_file_label = st.selectbox("Select MSCL Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                uploaded_file_path = file_row['file_path']
            else:
                st.warning("No MSCL file for this core.")
                uploaded_file_path = None  # Ensure the variable is defined

        if uploaded_file_path:
            with st.expander("Plot Settings"):
                try:
                    # Parse the selected MSCL file
                    df = parse_mscl_out_file(uploaded_file_path, selected_file_label)

                    if df is not None:
                        # Toggle to show/hide parsed data preview
                        show_parsed_data = st.checkbox("Show Parsed Data Preview", value=False)
                        if show_parsed_data:
                            st.write("Parsed MSCL Data Preview:")
                            st.dataframe(df)

                        # Check for numeric columns
                        numeric_columns = df.select_dtypes(include='number').columns.tolist()
                        if "SB DEPTH" in numeric_columns:
                            numeric_columns.remove("SB DEPTH")

                        if numeric_columns:
                            parameter = st.selectbox("Select Parameter to Plot", options=numeric_columns, index=0)
                            x_min = st.number_input('Set X-axis Min', value=float(df[parameter].min()), step=0.1)
                            x_max = st.number_input('Set X-axis Max', value=float(df[parameter].max()), step=0.1)
                            y_min = st.number_input('Set Y-axis Min (Depth)', value=float(df["SB DEPTH"].min()), step=0.1)
                            y_max = st.number_input('Set Y-axis Max (Depth)', value=float(df["SB DEPTH"].max()), step=0.1)
                        else:
                            st.warning("No numeric columns found for plotting.")
                            df = None  # Prevent further processing if no valid data
                    else:
                        st.warning("Could not parse the MSCL data file.")
                except Exception as e:
                    st.error(f"An error occurred while processing the file: {e}")
                    df = None

            if df is not None:
                # --- FILTERS (Dropout and LOWESS Smoothing) ---
                with st.expander("Filters"):
                    # Dropout Filter
                    enable_dropout = st.checkbox("Apply Dropout Filter", value=False)
                    if enable_dropout and numeric_columns:
                        filter_column = st.selectbox("Select Column for Dropout Filter", options=numeric_columns, index=0, key="dropout_column")
                        threshold = st.number_input(f"Set Threshold for '{filter_column}'", value=0.0, step=0.1, key="dropout_threshold")
                        filtered_df = df[df[filter_column] >= threshold].copy()
                    else:
                        filtered_df = df.copy()

                    # LOWESS Smoothing Filter
                    enable_smooth = st.checkbox("Apply LOWESS Smoothing", value=False)
                    if enable_smooth and numeric_columns:
                        smooth_column = st.selectbox("Select Column to Smooth", options=numeric_columns, index=0, key="smooth_column")
                        max_points = len(filtered_df)
                        default_width = min(20, max_points)
                        smooth_points = st.number_input("LOWESS Smoothing Width (number of points)", min_value=2, max_value=max_points, value=default_width, step=1)
                        lowess_frac = smooth_points / max_points
                        try:
                            from statsmodels.nonparametric.smoothers_lowess import lowess
                            valid = filtered_df[[smooth_column, "SB DEPTH"]].dropna()
                            smoothed = lowess(
                                endog=valid[smooth_column], exog=valid["SB DEPTH"], frac=lowess_frac, return_sorted=False
                            )
                            filtered_df.loc[valid.index, smooth_column + "_LOWESS"] = smoothed
                            smooth_param = smooth_column + "_LOWESS"
                        except ImportError:
                            st.error("statsmodels is required for LOWESS smoothing. Please install it with 'pip install statsmodels'.")
                            smooth_param = parameter
                    else:
                        smooth_param = parameter

                    # Parameter select: smoothed or original
                    plot_options = [parameter]
                    if enable_smooth and smooth_column + "_LOWESS" in filtered_df.columns:
                        plot_options.insert(0, smooth_column + "_LOWESS")
                    plot_param = st.selectbox("Parameter to Plot (original or smoothed)", plot_options, index=0)

                # --- COMPARISON ---
                with st.expander("Comparison Settings", expanded=st.session_state.get('comparison_settings_expanded', False)):
                    st.session_state['compare_enabled'] = st.checkbox("Compare with Another Core", value=st.session_state.get('compare_enabled', False))
                    if st.session_state['compare_enabled']:
                        other_core_options = core_options.copy()
                        del other_core_options[selected_core_label]
                        second_core_label = st.selectbox("Select Second Core", list(other_core_options.keys()))
                        second_core_id = other_core_options[second_core_label]
                        with get_connection() as conn:
                            query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
                            df_files_2 = pd.read_sql(query, conn, params=(second_core_id,))
                        if not df_files_2.empty:
                            selected_file_label_2 = st.selectbox("Select MSCL Data File for Second Core", df_files_2['file_name'])
                            file_row_2 = df_files_2[df_files_2['file_name'] == selected_file_label_2].iloc[0]
                            # Pass only the directory path
                            uploaded_file_path_2 = file_row_2['file_path']
                            st.write(f"Debug: file_path_2 = '{uploaded_file_path_2}'")
                            st.write(f"Debug: file_name_2 = '{selected_file_label_2}'")

                            try:
                                # Pass the directory path and file name to the parsing function
                                df2 = parse_mscl_out_file(uploaded_file_path_2, selected_file_label_2)
                                if df2 is not None:
                                    # Apply the same dropout filter to the second core if enabled
                                    if enable_dropout and filter_column in df2.columns:
                                        filtered_df2 = df2[df2[filter_column] >= threshold].copy()
                                    else:
                                        filtered_df2 = df2.copy()
                                    # Apply LOWESS smoothing to second core if enabled
                                    if enable_smooth and smooth_column in filtered_df2.columns:
                                        max_points2 = len(filtered_df2)
                                        lowess_frac2 = smooth_points / max_points2 if max_points2 > 0 else 0.2
                                        try:
                                            from statsmodels.nonparametric.smoothers_lowess import lowess
                                            valid2 = filtered_df2[[smooth_column, "SB DEPTH"]].dropna()
                                            smoothed2 = lowess(
                                                endog=valid2[smooth_column], exog=valid2["SB DEPTH"], frac=lowess_frac2, return_sorted=False
                                            )
                                            filtered_df2.loc[valid2.index, smooth_column + "_LOWESS"] = smoothed2
                                        except ImportError:
                                            st.error("statsmodels is required for LOWESS smoothing. Please install it with 'pip install statsmodels'.")
                                    # Plot type: Overlay or Side by Side
                                    plot_type = st.radio("Plot Type", ["Overlay", "Side by Side"])
                                    st.markdown("### Adjustments for Second Core")
                                    x_offset = st.number_input("X Offset", value=0.0, step=0.1)
                                    y_offset = st.number_input("Y Offset (Depth)", value=0.0, step=0.1)
                                    x_scale = st.number_input("X Scale (stretch/compress)", value=1.0, step=0.1, min_value=0.1)
                                    y_scale = st.number_input("Y Scale (stretch/compress)", value=1.0, step=0.1, min_value=0.1)
                                    with col2:
                                        plot_mscl_data_compare(
                                            df1=filtered_df,
                                            df2=filtered_df2,
                                            x_col=plot_param,
                                            y_col="SB DEPTH",
                                            core_name_1=selected_core_label,
                                            core_name_2=second_core_label,
                                            plot_type=plot_type,
                                            x_min=x_min,
                                            x_max=x_max,
                                            y_min=y_min,
                                            y_max=y_max,
                                            x_offset=x_offset,
                                            y_offset=y_offset,
                                            x_scale=x_scale,
                                            y_scale=y_scale
                                        )
                                else:
                                    st.warning("Could not parse second MSCL data file.")
                            except Exception as e:
                                st.error(f"An error occurred while processing the second file: {e}")
                        else:
                            st.info("No MSCL data files found for the selected second core.")
                    else:
                        if df is not None and not filtered_df.empty and plot_param:
                            with col2:
                                plot_mscl_data(
                                    df=filtered_df,
                                    x_col=plot_param,
                                    y_col="SB DEPTH",
                                    core_name=selected_core_label,
                                    x_min=x_min,
                                    x_max=x_max,
                                    y_min=y_min,
                                    y_max=y_max
                                )
        else:
            st.info("Please select an MSCL data file to visualize.")

# Only run this section if this file is run directly
if __name__ == "__main__":
    visualize_mscl_data()
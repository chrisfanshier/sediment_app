import os
import streamlit as st
import psycopg2
import pandas as pd
import numpy as np
from datetime import date, time
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import re

# Force wide layout for Streamlit
st.set_page_config(layout="wide")

# Custom CSS to reduce blank space
st.markdown(
    """
    <style>
    /* Reduce padding in the main content container */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0rem !important; /* Remove left padding */
        padding-right: 1rem !important;
    }
    /* Remove margin between the sidebar and main content */
    .css-1lcbmhc {
        margin-left: 0rem !important; /* Remove left margin */
        margin-right: 0rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Database connection
def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="sediment_cores",
        user="postgres",
        password="madmaxfuryroad"
    )

def fetch_cores():
    with get_connection() as conn:
        query = "SELECT core_id, core_name FROM cores ORDER BY core_name"
        return pd.read_sql(query, conn)

def parse_mscl_out_file(uploaded_file):
    try:
        lines = uploaded_file.read().decode("utf-8").splitlines()
        header_index = None
        for i, line in enumerate(lines):
            if line.strip().startswith("SB DEPTH"):
                header_index = i
                break
        if header_index is None:
            st.error("Could not find data header in file.")
            return None
        header_line = lines[header_index]
        header = re.findall(r"[A-Za-z0-9\^\-\(\)\/\s]+?(?=\s{2,}|\t|$)", header_line.strip())
        data_lines = lines[header_index + 2:]
        data = []
        for line in data_lines:
            if not line.strip():
                continue
            values = re.split(r'\s{2,}|\t', line.strip())
            while len(values) < len(header):
                values.append(None)
            data.append(values[:len(header)])
        df = pd.DataFrame(data, columns=header)
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except Exception as e:
                st.warning(f"Could not convert column '{col}' to numeric: {e}")
        df.dropna(how="all", inplace=True)
        return df
    except Exception as e:
        st.error(f"An error occurred while parsing the file: {e}")
        return None

def plot_mscl_data(df, x_col, y_col, core_name, x_min, x_max, y_min, y_max):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[x_col], 
        y=df[y_col], 
        mode='lines', 
        name=x_col, 
        line=dict(color='blue')
    ))
    if 'Den1' in df.columns and x_col != 'Den1':
        fig.add_trace(go.Scatter(
            x=df['Den1'], 
            y=df[y_col], 
            mode='lines', 
            name='Den1', 
            line=dict(color='red')
        ))
    fig.update_layout(
        title=f"{core_name}: {x_col} vs Depth",
        xaxis_title="Value",
        yaxis_title="Depth (SB DEPTH)",
        showlegend=True,
        height=1200
    )
    if x_min is not None and x_max is not None:
        fig.update_xaxes(range=[x_min, x_max])
    if y_min is not None and y_max is not None:
        fig.update_yaxes(range=[y_max, y_min], autorange=False)
    else:
        fig.update_yaxes(autorange='reversed')
    st.plotly_chart(fig)

def plot_mscl_data_compare(
    df1,
    df2,
    x_col,
    y_col,
    core_name_1,
    core_name_2,
    plot_type="Overlay",
    x_min=None,
    x_max=None,
    y_min=None,
    y_max=None,
    x_offset=0.0,
    y_offset=0.0,
    x_scale=1.0,
    y_scale=1.0
):
    if plot_type == "Side by Side":
        fig = make_subplots(rows=1, cols=2, shared_yaxes=True, subplot_titles=(core_name_1, core_name_2))
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines+markers',
            name=core_name_1,
            line=dict(color='blue')
        ), row=1, col=1)
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines+markers',
            name=core_name_2,
            line=dict(color='red')
        ), row=1, col=2)
        if x_min is not None and x_max is not None:
            fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
            fig.update_xaxes(range=[x_min, x_max], row=1, col=2)
        if y_min is not None and y_max is not None:
            fig.update_yaxes(range=[y_max, y_min], row=1, col=1)
            fig.update_yaxes(range=[y_max, y_min], row=1, col=2)
        else:
            fig.update_yaxes(autorange="reversed", row=1, col=1)
            fig.update_yaxes(autorange="reversed", row=1, col=2)
        fig.update_layout(
            title=f"Comparison of {core_name_1} and {core_name_2} for {x_col}",
            height=1200
        )
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df1[x_col],
            y=df1[y_col],
            mode='lines+markers',
            name=core_name_1,
            line=dict(color='blue')
        ))
        x2 = df2[x_col] * x_scale + x_offset
        y2 = df2[y_col] * y_scale + y_offset
        fig.add_trace(go.Scatter(
            x=x2,
            y=y2,
            mode='lines+markers',
            name=core_name_2,
            line=dict(color='red')
        ))
        fig.update_layout(
            title=f"Overlay: {core_name_1} vs {core_name_2} for {x_col}",
            xaxis=dict(
                range=[x_min, x_max] if x_min is not None and x_max is not None else None
            ),
            yaxis=dict(
                range=[y_max, y_min] if y_min is not None and y_max is not None else None,
                autorange="reversed" if y_min is None and y_max is None else False
            ),
            height=1200
        )
    st.plotly_chart(fig, use_container_width=True)

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
            with get_connection() as conn:
                query = "SELECT file_name, file_path FROM files WHERE core_id = %s AND file_type = 'MSCL Data'"
                df_files = pd.read_sql(query, conn, params=(selected_core_id,))
            if not df_files.empty:
                selected_file_label = st.selectbox("Select MSCL Data File", df_files['file_name'])
                file_row = df_files[df_files['file_name'] == selected_file_label].iloc[0]
                uploaded_file_path = file_row['file_path']
            else:
                st.warning("No MSCL file for this core.")
                uploaded_file_path = None

        if uploaded_file_path:
            with st.expander("Plot Settings"):
                try:
                    with open(uploaded_file_path, "rb") as file:
                        df = parse_mscl_out_file(file)
                    if df is not None:
                        show_parsed_data = st.checkbox("Show Parsed Data Preview", value=False)
                        if show_parsed_data:
                            st.write("Parsed MSCL Data Preview:")
                            st.dataframe(df)
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
                            df = None
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
                            uploaded_file_path_2 = file_row_2['file_path']
                            try:
                                with open(uploaded_file_path_2, "rb") as file2:
                                    df2 = parse_mscl_out_file(file2)
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
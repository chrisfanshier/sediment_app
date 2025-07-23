import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import os

st.title("SB DEPTH Inversion App")

uploaded_file = st.file_uploader("Upload your .out file", type=["out"])
if uploaded_file:
    # For output file naming
    input_name = uploaded_file.name
    base, ext = os.path.splitext(input_name)
    output_name = f"{base}_st_invert_only.out"

    # Read all lines
    lines = uploaded_file.getvalue().decode("utf-8").splitlines(keepends=True)
    # --- Step 1: Find header row ---
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("SB DEPTH"):
            header_idx = i
            break
    if header_idx is None:
        st.error("Header 'SB DEPTH' not found.")
        st.stop()
    data_start = header_idx + 2  # Header + units

    # --- Step 2: Read data into DataFrame ---
    col_names = lines[header_idx].strip().split('\t')
    data_text = "".join(lines[data_start:])
    df = pd.read_csv(io.StringIO(data_text), sep='\t', names=col_names, engine='python')

    # --- Rename highest numeric SECT NUM to "cal_sect" ---
    sect_nums_numeric = pd.to_numeric(df['SECT NUM'], errors='coerce')
    max_numeric_sect = sect_nums_numeric.max()
    df.loc[sect_nums_numeric == max_numeric_sect, 'SECT NUM'] = "cal_sect"

    # --- create an inverted dataframe ---
    df_invert = df.copy()
    if not df_invert.empty:
        min_depth = df_invert["SB DEPTH"].min()
        max_depth = df_invert["SB DEPTH"].max()
        df_invert["SB DEPTH"] = max_depth + min_depth - df_invert["SB DEPTH"]
        df_invert = df_invert.iloc[::-1].reset_index(drop=True)

    # --- invert section numbers ---
    sect_nums = pd.to_numeric(df_invert['SECT NUM'], errors='coerce')
    n_sections = int(sect_nums.max())

    def invert_sect_num(val):
        try:
            i = int(val)
            return n_sections + 1 - i
        except (ValueError, TypeError):
            return val

    df_invert['SECT NUM'] = df_invert['SECT NUM'].apply(invert_sect_num)

    # --- plotting ---
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                        subplot_titles=("Original", "Inverted"))
    fig.add_trace(
        go.Scatter(
            x=df["Den1"],
            y=df["SB DEPTH"],
            mode='markers+lines',
            name="Original"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df_invert["Den1"],
            y=df_invert["SB DEPTH"],
            mode='markers+lines',
            name="Inverted",
            marker=dict(color='orange')
        ),
        row=1, col=2
    )
    fig.update_yaxes(autorange="reversed", title_text="SB DEPTH", row=1, col=1)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    fig.update_xaxes(title_text="Den1", row=1, col=1)
    fig.update_xaxes(title_text="Den1", row=1, col=2)
    fig.update_layout(
        title="SB DEPTH Inversion Check (Interactive)",
        height=600, width=1000,
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- export to a new .out file ---
    # Extract header lines up to and including units line (e.g. 'Ohm.m')
    header_lines = []
    data_start_out = None
    for i, line in enumerate(lines):
        header_lines.append(line)
        if "Ohm.m" in line:  # Adjust this if your units line is different!
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                header_lines.append(lines[j])
                j += 1
            data_start_out = j
            break
    if data_start_out is None:
        st.error("Units line (e.g. 'Ohm.m') not found. Please adjust the script for your file.")
        st.stop()

    # Prepare output as bytes
    output_buf = io.StringIO()
    output_buf.writelines(header_lines)
    df_invert.to_csv(output_buf, sep='\t', index=False, header=False, float_format="%.4f")
    st.download_button(
        label="Download processed .out file",
        data=output_buf.getvalue().encode(),
        file_name=output_name,
        mime="text/plain"
    )
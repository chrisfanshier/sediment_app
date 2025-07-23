import streamlit as st
import re
from datetime import datetime

def process_and_invert(file_content, out_filename="inverted.out"):
    lines = file_content.splitlines()
    # Find header and data
    col_line_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("SB DEPTH"):
            col_line_idx = i
            break
    if col_line_idx is None or col_line_idx + 2 >= len(lines):
        raise ValueError("Could not find column header. Is this a v7.9 .out file?")
    header_lines = lines[:col_line_idx + 2]  # includes units line

    # Read data rows (skip blank lines)
    data_lines = [l for l in lines[col_line_idx + 2:] if l.strip()]

    # Parse data rows into lists, robust on whitespace
    data_rows = [re.split(r'\s+', l.strip()) for l in data_lines]
    # Find SECT NUM column index (should be 1)
    col_names = re.split(r'\s+', lines[col_line_idx].strip())
    try:
        sect_num_idx = col_names.index("SECT NUM")
    except Exception:
        sect_num_idx = 1  # fallback

    # Find SB DEPTH index (should be 0)
    try:
        sb_depth_idx = col_names.index("SB DEPTH")
    except Exception:
        sb_depth_idx = 0

    # Split calibration and core rows
    calibration_rows = []
    core_rows = []
    cal_done = False
    for r in data_rows:
        # Defensive: some rows may be short, skip blanks
        if len(r) <= max(sect_num_idx, sb_depth_idx):
            continue
        # Calibration rows must be at the top, so once we hit non-cal, we only add to core_rows
        if (not cal_done) and r[sect_num_idx].lower().startswith("cal"):
            calibration_rows.append(r)
        else:
            cal_done = True
            core_rows.append(r)

    # Get SB DEPTHs as floats for core rows
    try:
        sb_depths = [float(r[sb_depth_idx]) for r in core_rows]
    except Exception as e:
        raise ValueError(f"Could not parse SB DEPTH column in core rows: {e}")

    if sb_depths:
        min_depth = min(sb_depths)
        max_depth = max(sb_depths)
        # Invert SB DEPTH for ALL core rows, using the full range
        inverted_depths = [f"{max_depth + min_depth - d:.1f}" for d in sb_depths]
        # Reverse order and assign new depths
        new_core_rows = []
        for new_depth, orig_row in zip(inverted_depths[::-1], core_rows[::-1]):
            orig_row[sb_depth_idx] = new_depth
            new_core_rows.append(orig_row)
    else:
        new_core_rows = []

    # Compose output
    output = "\n".join(header_lines) + "\n"
    # Calibration rows (unchanged order)
    for row in calibration_rows:
        output += "\t".join(row) + "\n"
    # Core rows (reversed and with new depths)
    for row in new_core_rows:
        output += "\t".join(row) + "\n"
    return output

st.title("Invert Core Depth in Geotek MSCL .out File (with Calibration Section)")
st.write("""
Upload a new-format Geotek MSCL .out file (v7.9 style).  
Calibration rows (SECT NUM = "cal") at the top remain unchanged;  
core data is inverted so SB DEPTH is flipped for reverse scans.
""")

uploaded_file = st.file_uploader("Choose a new-format .out file", type=["out", "txt"])
if uploaded_file is not None:
    file_content = uploaded_file.read().decode("utf-8", errors="ignore")
    out_filename = uploaded_file.name.replace(".out", "_inverted.out")
    try:
        converted = process_and_invert(file_content, out_filename=out_filename)
        st.success("Inversion complete! Download your new file below.")
        st.download_button(
            label="Download inverted file",
            data=converted,
            file_name=out_filename,
            mime="text/plain"
        )
        st.text_area("Preview (first 30 lines)", "\n".join(converted.splitlines()[:30]), height=400)
    except Exception as e:
        st.error(f"Error: {e}")
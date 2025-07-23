import streamlit as st
import io
import re
from datetime import datetime

def convert_old_to_new(file_content, out_filename="converted.out"):
    lines = file_content.splitlines()
    # Find where data starts (after headers)
    data_start = 0
    for i, line in enumerate(lines):
        if re.match(r"[-\d.]+\s", line):  # Data rows start with a number (possibly negative)
            data_start = i
            break

    # New header
    now = datetime.now()
    header = [
        f"Geotek MSCL 7.9 - {out_filename} created at {now.strftime('%H:%M:%S on %m/%d/%Y')}.\n",
        "\n",
        "Processing Parameters\n",
        "\n",
        "CT\tRCT=11.35\tW=1.13\n",
        "PWAmp\tA=1\tB=0\n",
        "PWVel\tPTO=25.98\n",
        "Den1\tA=-.00039\tB=-.04384\tC=10.21151\n",
        "MS1\tA=1\tB=0\tDen=1\tLD=14\t\n",
        "FP\tMGD=2.75\tWD=1.026\t\n",
        "RES\tA=.0031\tB=-.0146\tp=0\t\n",
        "\n",
        "SB DEPTH\tSECT NUM\tSECT DEPTH\tCT\tPWAmp\tPWVel\tDen1\tMS1\tImp\tFP\tRES\n",
        "cm\t\tcm\tcm\t\tm/s\tg/cc\tx 10^-8 (m^3/kg)\t\t\tOhm.m\n",
    ]

    # Process data rows
    data_lines = lines[data_start:]
    converted_rows = []
    for line in data_lines:
        if not line.strip():
            continue
        fields = re.split(r'\s+', line.strip())
        # Old: SB DEPTH, SECT NUM, SECT DEPTH, ST, PWAmp, PWVel, Den1, MS1, Imp, FP, RES
        # Convert SB DEPTH from m to cm
        try:
            sb_depth_cm = float(fields[0]) * 100
        except:
            sb_depth_cm = fields[0]
        out_fields = [
            f"{sb_depth_cm:.1f}",
            fields[1],
            fields[2],
            fields[3],  # CT (was ST)
            fields[4],  # PWAmp
            fields[5] if len(fields) > 5 else '',  # PWVel
            fields[6] if len(fields) > 6 else '',  # Den1
            fields[7] if len(fields) > 7 else '',  # MS1
            fields[8] if len(fields) > 8 else '',  # Imp
            fields[9] if len(fields) > 9 else '',  # FP
            fields[10] if len(fields) > 10 else '',  # RES
        ]
        converted_rows.append("\t".join(out_fields) + "\n")

    # Concatenate new file content
    output_content = "".join(header) + "".join(converted_rows)
    return output_content

st.title("Old Geotek MSCL .out File Converter")
st.write("""
Upload an old-format Geotek MSCL .out file below.  
The app will convert it to the new format, which you can then download and use with your plotting utility.
""")

uploaded_file = st.file_uploader("Choose an old-format .out file", type=["out", "txt"])
if uploaded_file is not None:
    file_content = uploaded_file.read().decode("utf-8", errors="ignore")
    out_filename = uploaded_file.name.replace(".out", "_converted.out")
    converted = convert_old_to_new(file_content, out_filename=out_filename)
    st.success("Conversion complete! Download your new-format file below.")
    st.download_button(
        label="Download converted file",
        data=converted,
        file_name=out_filename,
        mime="text/plain"
    )
    st.text_area("Preview (first 30 lines)", "\n".join(converted.splitlines()[:30]), height=400)
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from trip_detector import detect_trip_time
from piston_position import calculate_piston_position, get_piston_summary

st.set_page_config(page_title="Piston Calculator with Trip Detection", layout="wide")
st.title("Piston Position Calculator with Trip Detection")

# === FILE UPLOAD ===
uploaded_file = st.file_uploader("Upload CSV export from Sediment App", type="csv")

if uploaded_file is not None:
    # Read CSV, skipping header comments
    content = uploaded_file.read().decode('utf-8')
    lines = content.split('\n')
    
    # Find where data starts
    skiprows = 0
    for i, line in enumerate(lines):
        if line.startswith('datetime'):
            skiprows = i
            break
    
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file, skiprows=skiprows)
    df.columns = df.columns.str.strip()
    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    
    # === AUTO-DETECT COLUMNS ===
    st.subheader("🔍 Column Detection")
    
    depth_cols = [col for col in df.columns if 'Depth' in col]
    weight_stand_cols = [col for col in df.columns if 'Weight Stand' in col]
    release_cols = [col for col in df.columns if 'Release Device' in col]
    tension_cols = [col for col in df.columns if 'Tension' in col]
    
    weight_stand_col = weight_stand_cols[0] if weight_stand_cols else None
    release_col = release_cols[0] if release_cols else None
    tension_col = tension_cols[0] if tension_cols else None
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write("**Detected Columns:**")
        st.text(f"📊 Weight Stand:\n{weight_stand_col}")
        st.text(f"🔓 Release Device:\n{release_col}")
    
    with col2:
        st.write("**Depth Columns:**")
        for i, col in enumerate(depth_cols[:3], 1):
            st.text(f"{i}. {col[:40]}")
    
    with col3:
        st.write("**Other:**")
        st.text(f"⚡ Tension:\n{tension_col}")
    
    # === TAB 1: TRIP DETECTION ===
    tab1, tab2, tab3 = st.tabs(["1️⃣ Detect Trip Time", "2️⃣ Adjust Sensor Offsets", "3️⃣ Calculate Piston Position"])
    
    with tab1:
        st.header("Step 1: Detect Trip Time")
        st.write("Analyze tension and sensor data to find when the coring device tripped")
        
        # Trip detection parameters
        col1, col2 = st.columns(2)
        
        with col1:
            std_threshold = st.slider(
                "RBR Std Deviation Threshold",
                min_value=0.001,
                max_value=0.1,
                value=0.01,
                step=0.001,
                format="%.4f",
                help="Lower = earlier RBR detection, Higher = later detection"
            )
        
        with col2:
            edge_buffer = st.slider(
                "Edge Buffer (samples)",
                min_value=100,
                max_value=2000,
                value=500,
                step=50,
                help="Samples to exclude from start/end"
            )
        
        if st.button("🔍 Detect Trip Time", type="primary", use_container_width=True):
            try:
                with st.spinner("Analyzing data..."):
                    trip_time, confidence, diag = detect_trip_time(
                        df,
                        tension_col=tension_col,
                        depth_cols=depth_cols,
                        std_threshold=std_threshold,
                        edge_buffer=edge_buffer
                    )
                
                # Store in session state
                st.session_state.trip_time = trip_time
                st.session_state.trip_confidence = confidence
                st.session_state.trip_diag = diag
                
                # Display results
                st.success(f"✅ Trip Time Detected: `{trip_time}`")
                st.metric("Confidence", f"{confidence:.0%}")
                
                st.info(
                    f"**⏱️ RBR Time Offset:** {diag['rbr_trip_estimate']['offset_from_winch_seconds']:.3f} seconds\n\n"
                    f"*Add this to RBR timestamps to align with winch*"
                )
                
                # Create trip detection visualization
                from scipy import signal
                
                winch_trip_idx = diag['winch_trip_estimate']['idx']
                rbr_trip_idx = diag['rbr_trip_estimate']['idx']
                
                fig = make_subplots(
                    rows=3, cols=1,
                    subplot_titles=("Winch Tension", "Depth Sensors", "Velocity Divergence (RBR)"),
                    specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
                    vertical_spacing=0.1,
                    shared_xaxes=True
                )
                
                x_vals = list(range(len(df)))
                colors = ['blue', 'green', 'orange']
                
                # Row 1: Tension
                tension = df[tension_col].fillna(method='ffill').fillna(method='bfill').values
                fig.add_trace(
                    go.Scatter(x=x_vals, y=tension, mode='lines', name='Tension',
                              line=dict(color='red', width=2)),
                    row=1, col=1
                )
                fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2,
                             annotation_text=f"Trip: idx={winch_trip_idx}",
                             annotation_position="top right", row=1, col=1)
                fig.update_yaxes(title_text="Tension (lbs)", row=1, col=1)
                
                # Row 2: Depths
                for i, col in enumerate(depth_cols):
                    fig.add_trace(
                        go.Scatter(x=x_vals, y=df[col], mode='lines', name=col,
                                  line=dict(color=colors[i % len(colors)], width=1.5)),
                        row=2, col=1
                    )
                fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=2, col=1)
                fig.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=2, col=1)
                fig.update_yaxes(title_text="Depth (m)", autorange="reversed", row=2, col=1)
                
                # Row 3: Divergence
                depths = np.array([df[col].interpolate().fillna(method='ffill').fillna(method='bfill').values 
                                 for col in depth_cols])
                depths_smooth = np.array([signal.savgol_filter(d, window_length=51, polyorder=4) for d in depths])
                d_depths = np.diff(depths_smooth, axis=1)
                d_depths_smooth = np.array([signal.savgol_filter(vel, window_length=31, polyorder=2) for vel in d_depths])
                velocity_std = np.std(d_depths_smooth, axis=0)
                
                fig.add_trace(
                    go.Scatter(x=x_vals[:-1], y=velocity_std, mode='lines', name='Velocity Std Dev',
                              line=dict(color='purple', width=3)),
                    row=3, col=1
                )
                fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=3, col=1)
                fig.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=3, col=1)
                fig.update_yaxes(title_text="Divergence (m/sample²)", row=3, col=1)
                fig.update_xaxes(title_text="Sample Index", row=3, col=1)
                
                fig.update_layout(height=900, hovermode='x unified', showlegend=True,
                                 title_text="Trip Detection (Red dash=Winch, Green dot=RBR)")
                st.plotly_chart(fig, use_container_width=True)
                
                # Diagnostics
                with st.expander("📊 Detailed Diagnostics"):
                    st.json(diag)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
    
    # === TAB 2: SENSOR OFFSET ADJUSTMENT ===
    with tab2:
        st.header("Step 2: Adjust Sensor Offsets")
        st.write("""
        **Align sensor timestamps with winch (canonical) time:**
        1. Enter time offsets for each sensor file (defaults to detected offset)
        2. View the updated plot below
        3. Click "Save Adjusted Data" to lock in the adjustments for calculation
        """)
        
        if "trip_time" not in st.session_state:
            st.warning("⚠️ Please detect trip time in Step 1 first")
        else:
            # Extract sensor file names from depth columns
            sensor_files = {}
            for col in depth_cols:
                parts = col.split('_')
                if len(parts) >= 4:
                    file_id = '_'.join(parts[1:4])
                    sensor_type = parts[0]
                    
                    if file_id not in sensor_files:
                        sensor_files[file_id] = {
                            'type': sensor_type,
                            'columns': []
                        }
                    sensor_files[file_id]['columns'].append(col)
            
            # Initialize session state for offsets if not exists
            if "sensor_offsets" not in st.session_state:
                st.session_state.sensor_offsets = {}
                suggested_offset = st.session_state.trip_diag['rbr_trip_estimate']['offset_from_winch_seconds']
                for file_id in sensor_files:
                    st.session_state.sensor_offsets[file_id] = suggested_offset
            
            # Offset input section
            st.subheader("⏱️ Enter Time Offsets (seconds)")
            st.info(f"💡 Suggested offset from trip detection: {st.session_state.trip_diag['rbr_trip_estimate']['offset_from_winch_seconds']:.3f}s")
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.write("**File ID**")
            with col2:
                st.write("**Type**")
            with col3:
                st.write("**Offset (seconds)**")
            
            st.markdown("---")
            
            for file_id in sorted(sensor_files.keys()):
                sensor_type = sensor_files[file_id]['type']
                
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.text(file_id)
                
                with col2:
                    st.text(sensor_type)
                
                with col3:
                    offset = st.number_input(
                        f"Offset {file_id}",
                        value=st.session_state.sensor_offsets.get(file_id, 0.0),
                        step=0.1,
                        format="%.1f",
                        label_visibility="collapsed",
                        key=f"offset_{file_id}"
                    )
                    st.session_state.sensor_offsets[file_id] = offset
            
            st.markdown("---")
            
            # Create plot with current offsets applied
            st.subheader("📊 Adjusted Data Preview")
            
            fig = go.Figure()
            
            x_vals = df['datetime']
            
            # Adjusted sensor data with current offsets
            for col in depth_cols:
                parts = col.split('_')
                if len(parts) >= 4:
                    file_id = '_'.join(parts[1:4])
                    offset_seconds = st.session_state.sensor_offsets[file_id]
                    adjusted_datetime = x_vals + pd.Timedelta(seconds=offset_seconds)
                    
                    sensor_type = parts[0]
                    label = f'{sensor_type} (offset: {offset_seconds:.1f}s)'
                    
                    fig.add_trace(go.Scatter(
                        x=adjusted_datetime, y=df[col],
                        mode='lines', name=label,
                        line=dict(width=2)
                    ))
            
            # Winch reference (Weight Stand) - always at original time
            fig.add_trace(go.Scatter(
                x=x_vals, y=df[weight_stand_col],
                mode='lines', name='Weight Stand (Winch - Reference)',
                line=dict(color='black', width=2.5)
            ))
            
            fig.update_layout(
                title="Sensor Data with Applied Time Offsets",
                xaxis_title="Time",
                yaxis_title="Depth (m)",
                hovermode='x unified',
                height=500,
                template='plotly_white'
            )
            fig.update_yaxes(autorange="reversed")
            
            st.plotly_chart(fig, use_container_width=True)
            
            st.info("✅ Adjust the offset values above to align the sensors with the winch reference (black line)")
            
            # Save adjusted data button
            if st.button("💾 Save Adjusted Data for Calculation", type="primary", use_container_width=True):
                # Create adjusted dataframe with time-shifted columns
                df_adjusted = df.copy()
                
                for col in depth_cols:
                    parts = col.split('_')
                    if len(parts) >= 4:
                        file_id = '_'.join(parts[1:4])
                        offset_seconds = st.session_state.sensor_offsets[file_id]
                        # Store the offset info for reference
                
                st.session_state.df_final = df_adjusted
                st.session_state.offset_mapping = dict(st.session_state.sensor_offsets)
                st.session_state.offsets_saved = True
                st.success("✅ Adjusted data saved! Move to Step 3 to calculate piston position.")
    
    # === TAB 3: PISTON POSITION CALCULATION ===
    with tab3:
        st.header("Step 3: Calculate Piston Position")
        st.write("Calculate piston position based on detected trip time and device parameters")
        
        if "trip_time" not in st.session_state:
            st.warning("⚠️ Please detect trip time in Step 1 first")
        else:
            trip_time = st.session_state.trip_time
            
            # Check if adjusted data is available
            if "offsets_saved" not in st.session_state or not st.session_state.offsets_saved:
                st.info("ℹ️ Using original data (no time offset adjustments)")
                df_to_use = df
            else:
                st.info("✅ Using adjusted data with time offset corrections")
                df_to_use = st.session_state.df_final
                
                # Show applied offsets
                with st.expander("📋 Applied Sensor Offsets"):
                    offset_data = []
                    for file_id, offset in st.session_state.offset_mapping.items():
                        offset_data.append({'File ID': file_id, 'Offset (seconds)': offset})
                    st.dataframe(pd.DataFrame(offset_data), use_container_width=True)
            
            # Parameters
            col1, col2, col3 = st.columns(3)
            
            with col1:
                barrel_length = st.number_input(
                    "Barrel Length (m)",
                    value=8.5,
                    step=0.1,
                    help="Length of the piston corer barrel"
                )
            
            with col2:
                scope = st.number_input(
                    "Scope (m)",
                    value=5.0,
                    step=0.1,
                    help="Scope of the coring device"
                )
            
            with col3:
                offset_constant = st.number_input(
                    "Offset Constant (m)",
                    value=4.0,
                    step=0.1,
                    help="Constant offset"
                )
            
            st.info(f"**Trip Time:** {trip_time}")
            
            if st.button("🧮 Calculate Piston Position", type="primary", use_container_width=True):
                try:
                    with st.spinner("Calculating..."):
                        summary = get_piston_summary(
                            df_to_use,
                            barrel_length=barrel_length,
                            trip_time=trip_time,
                            scope=scope,
                            offset_constant=offset_constant,
                            time_col='datetime',
                            weight_stand_col=weight_stand_col,
                            release_col=release_col
                        )
                    
                    result_df = summary['df']
                    st.session_state.piston_results = result_df
                    
                    # Summary metrics
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Min Depth", f"{summary['min_depth']:.2f} m")
                    with col2:
                        st.metric("Max Depth", f"{summary['max_depth']:.2f} m")
                    with col3:
                        st.metric("Mean Depth", f"{summary['mean_depth']:.2f} m")
                    with col4:
                        st.metric("Valid Points", summary['valid_points'])
                    
                    # Create visualization - Piston Position Plot
                    fig = go.Figure()
                    
                    x_vals = result_df['datetime']
                    
                    # Weight Stand
                    fig.add_trace(go.Scatter(
                        x=x_vals, y=result_df[weight_stand_col],
                        mode='lines', name='Weight Stand',
                        line=dict(color='blue', width=1.5)
                    ))
                    
                    # Release Device
                    fig.add_trace(go.Scatter(
                        x=x_vals, y=result_df[release_col],
                        mode='lines', name='Release Device',
                        line=dict(color='green', width=1.5)
                    ))
                    
                    # Piston Position
                    fig.add_trace(go.Scatter(
                        x=x_vals, y=result_df['piston_position'],
                        mode='lines', name='Piston Position',
                        line=dict(color='red', width=2.5)
                    ))
                    
                    # Trip time line
                    fig.add_vline(x=trip_time, line_dash="dash", line_color="orange", line_width=2)
                    
                    # Switch to release line (if it happened)
                    if summary['switch_time'] is not None:
                        fig.add_vline(x=summary['switch_time'], line_dash="dot", line_color="purple", line_width=2)
                    
                    fig.update_layout(
                        title="Depth Measurements During Coring",
                        xaxis_title="Time",
                        yaxis_title="Depth (m)",
                        hovermode='x unified',
                        height=500,
                        template='plotly_white'
                    )
                    fig.update_yaxes(autorange="reversed")
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Display results table
                    st.subheader("📋 Results")
                    display_cols = ['datetime', weight_stand_col, release_col, 'piston_position']
                    st.dataframe(result_df[display_cols], use_container_width=True)
                    
                    # Download button
                    csv_data = result_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Results (CSV)",
                        data=csv_data,
                        file_name=f"piston_position_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    # Show trip detection diagnostic plot if available
                    if "trip_diag" in st.session_state:
                        with st.expander("📊 Trip Detection Diagnostics"):
                            from scipy import signal
                            
                            diag = st.session_state.trip_diag
                            winch_trip_idx = diag['winch_trip_estimate']['idx']
                            rbr_trip_idx = diag['rbr_trip_estimate']['idx']
                            
                            fig_diag = make_subplots(
                                rows=3, cols=1,
                                subplot_titles=("Winch Tension", "Depth Sensors", "Velocity Divergence (RBR)"),
                                specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
                                vertical_spacing=0.1,
                                shared_xaxes=True
                            )
                            
                            x_vals_idx = list(range(len(df_to_use)))
                            colors = ['blue', 'green', 'orange']
                            
                            # Row 1: Tension
                            tension = df_to_use[tension_col].fillna(method='ffill').fillna(method='bfill').values
                            fig_diag.add_trace(
                                go.Scatter(x=x_vals_idx, y=tension, mode='lines', name='Tension',
                                          line=dict(color='red', width=2)),
                                row=1, col=1
                            )
                            fig_diag.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2,
                                             annotation_text=f"Trip: idx={winch_trip_idx}",
                                             annotation_position="top right", row=1, col=1)
                            fig_diag.update_yaxes(title_text="Tension (lbs)", row=1, col=1)
                            
                            # Row 2: Depths
                            for i, col in enumerate(depth_cols):
                                fig_diag.add_trace(
                                    go.Scatter(x=x_vals_idx, y=df_to_use[col], mode='lines', name=col,
                                              line=dict(color=colors[i % len(colors)], width=1.5)),
                                    row=2, col=1
                                )
                            fig_diag.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=2, col=1)
                            fig_diag.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=2, col=1)
                            fig_diag.update_yaxes(title_text="Depth (m)", autorange="reversed", row=2, col=1)
                            
                            # Row 3: Divergence
                            depths = np.array([df_to_use[col].interpolate().fillna(method='ffill').fillna(method='bfill').values 
                                             for col in depth_cols])
                            depths_smooth = np.array([signal.savgol_filter(d, window_length=51, polyorder=4) for d in depths])
                            d_depths = np.diff(depths_smooth, axis=1)
                            d_depths_smooth = np.array([signal.savgol_filter(vel, window_length=31, polyorder=2) for vel in d_depths])
                            velocity_std = np.std(d_depths_smooth, axis=0)
                            
                            fig_diag.add_trace(
                                go.Scatter(x=x_vals_idx[:-1], y=velocity_std, mode='lines', name='Velocity Std Dev',
                                          line=dict(color='purple', width=3)),
                                row=3, col=1
                            )
                            fig_diag.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=3, col=1)
                            fig_diag.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=3, col=1)
                            fig_diag.update_yaxes(title_text="Divergence (m/sample²)", row=3, col=1)
                            fig_diag.update_xaxes(title_text="Sample Index", row=3, col=1)
                            
                            fig_diag.update_layout(height=900, hovermode='x unified', showlegend=True,
                                                 title_text="Trip Detection (Red dash=Winch, Green dot=RBR)")
                            st.plotly_chart(fig_diag, use_container_width=True)
                    
                except Exception as e:
                    st.error(f"❌ Calculation error: {str(e)}")
                    import traceback
                    st.write(traceback.format_exc())

else:
    st.info("👆 Upload a CSV export from Sediment App to begin")
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from trip_detector import detect_trip_time

st.title("🎣 Trip Time Detector")

uploaded_file = st.file_uploader("Upload CSV export from Sediment App", type="csv")

if uploaded_file:
    # Find where the actual data starts by looking for the header line
    content = uploaded_file.read().decode('utf-8')
    lines = content.split('\n')
    
    # Find the line with "datetime" in it
    skiprows = 0
    for i, line in enumerate(lines):
        if line.startswith('datetime'):
            skiprows = i
            break
    
    # Re-read with correct skiprows
    uploaded_file.seek(0)
    df = pd.read_csv(uploaded_file, skiprows=skiprows, sep=',', quotechar='"', parse_dates=['datetime'])
    
    # Clean column names (remove extra whitespace)
    df.columns = df.columns.str.strip()
    
    st.write("**Data shape:**", df.shape)
    st.write("**Columns:**", list(df.columns))
    st.write("**First few rows:**")
    st.write(df.head(10))
    
    # Add threshold adjustment sliders
    st.sidebar.header("Trip Detection Parameters")
    
    std_threshold = st.sidebar.slider(
        "RBR Std Deviation Threshold",
        min_value=0.001,
        max_value=0.1,
        value=0.01,
        step=0.001,
        format="%.4f",
        help="Lower = earlier RBR detection, Higher = later detection"
    )
    
    edge_buffer = st.sidebar.slider(
        "Edge Buffer (samples)",
        min_value=100,
        max_value=2000,
        value=500,
        step=50,
        help="Samples to exclude from start/end to avoid edge effects"
    )
    
    if st.button("Detect Trip Time"):
        try:
            trip_time, confidence, diag = detect_trip_time(df, std_threshold=std_threshold, edge_buffer=edge_buffer)
            
            # Use values from diagnostics
            trip_time = pd.to_datetime(diag['trip_time'])
            confidence = diag['confidence']
            winch_trip_idx = diag['winch_trip_estimate']['idx']
            rbr_trip_idx = diag['rbr_trip_estimate']['idx']
            offset_seconds = diag['rbr_trip_estimate']['offset_from_winch_seconds']
            
            st.success(f"### ✅ Trip Time: `{trip_time}` \n**Confidence: {confidence:.0%}**")
            st.info(f"**⏱️ RBR Time Offset: {offset_seconds:.3f} seconds** (add this to RBR timestamps to align with winch)")
            
            # Create coupled Plotly subplots
            fig = make_subplots(
                rows=4, cols=1,
                subplot_titles=("Winch Tension", "Depth Sensors", "Raw Depth Velocity", "Smoothed Depth Velocity (Divergence Metric)"),
                specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}]],
                vertical_spacing=0.08,
                shared_xaxes=True  # Couple all x-axes together
            )
            
            x_vals = list(range(len(df)))
            depth_cols = [col for col in df.columns if 'Depth' in col]
            
            # Row 1: Tension
            tension_vals = df['WINCH_Tension'].fillna(method='ffill').values
            fig.add_trace(
                go.Scatter(x=x_vals, y=tension_vals, mode='lines', name='Tension', 
                          line=dict(color='red', width=2), hovertemplate='<b>Tension</b><br>idx: %{x}<br>value: %{y:.0f}<extra></extra>'),
                row=1, col=1
            )
            fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2,
                         annotation_text=f"Winch Trip (idx={winch_trip_idx})", 
                         annotation_position="top right", row=1, col=1)
            fig.update_yaxes(title_text="Tension (lbs)", row=1, col=1)
            
            # Row 2: Depths (inverted Y-axis)
            colors = ['blue', 'green', 'orange']
            for i, col in enumerate(depth_cols):
                fig.add_trace(
                    go.Scatter(x=x_vals, y=df[col], mode='lines', name=col, 
                              line=dict(color=colors[i], width=1.5),
                              hovertemplate='<b>' + col + '</b><br>idx: %{x}<br>depth: %{y:.2f}m<extra></extra>'),
                    row=2, col=1
                )
            fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=2, col=1)
            fig.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=2, col=1)
            fig.update_yaxes(title_text="Depth (m)", autorange="reversed", row=2, col=1)  # Inverted
            
            # Row 3: Raw depth velocities
            from scipy import signal
            import numpy as np
            depths = np.array([df[col].interpolate().fillna(method='ffill').fillna(method='bfill').values for col in depth_cols])
            depths_smooth = np.array([signal.savgol_filter(d, window_length=51, polyorder=4) for d in depths])
            d_depths = np.diff(depths_smooth, axis=1)
            
            for i, col in enumerate(depth_cols):
                fig.add_trace(
                    go.Scatter(x=x_vals[:-1], y=d_depths[i], mode='lines', name=f"{col[:40]} raw velocity", 
                              line=dict(color=colors[i], width=1.5),
                              hovertemplate='<b>' + col + ' velocity</b><br>idx: %{x}<br>velocity: %{y:.4f}m/sample<extra></extra>'),
                    row=3, col=1
                )
            fig.add_hline(y=0, line_color="black", line_width=0.5, row=3, col=1)
            fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=3, col=1)
            fig.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=3, col=1)
            fig.update_yaxes(title_text="Velocity (m/sample)", row=3, col=1)
            
            # Row 4: Smoothed velocity and divergence std
            d_depths_smooth = np.array([signal.savgol_filter(vel, window_length=21, polyorder=2) for vel in d_depths])
            velocity_std = np.std(d_depths_smooth, axis=0)
            
            for i, col in enumerate(depth_cols):
                fig.add_trace(
                    go.Scatter(x=x_vals[:-1], y=d_depths_smooth[i], mode='lines', name=f"{col[:40]} smoothed velocity", 
                              line=dict(color=colors[i], width=2, dash='dash'),
                              hovertemplate='<b>' + col + ' smoothed velocity</b><br>idx: %{x}<br>velocity: %{y:.4f}m/sample<extra></extra>'),
                    row=4, col=1
                )
            
            # Add divergence std
            fig.add_trace(
                go.Scatter(x=x_vals[:-1], y=velocity_std, mode='lines', name='Velocity Std Dev (divergence)', 
                          line=dict(color='purple', width=3),
                          hovertemplate='<b>Divergence (Std Dev)</b><br>idx: %{x}<br>std: %{y:.6f}<extra></extra>'),
                row=4, col=1
            )
            fig.add_hline(y=0, line_color="black", line_width=0.5, row=4, col=1)
            fig.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", line_width=2, row=4, col=1)
            fig.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", line_width=2, row=4, col=1)
            fig.update_yaxes(title_text="Velocity (m/sample)", row=4, col=1)
            
            # Update layout with shared x-axis
            fig.update_xaxes(title_text="Sample index", row=4, col=1)
            fig.update_layout(
                height=1200, 
                hovermode='x unified',
                showlegend=True,
                title_text="Trip Detection (Red dashed=Winch, Green dot=RBR)"
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            st.write("**Diagnostics:**")
            st.json(diag)
            
            # Debug plots
            if st.checkbox("Show Debug Plots (smoothed signals & derivatives)"):
                tension = df['WINCH_Tension'].fillna(method='ffill').fillna(method='bfill').values
                tension_smooth = signal.savgol_filter(tension, window_length=11, polyorder=2)
                d_tension = np.diff(tension_smooth)
                
                depth_spread = np.max(depths_smooth, axis=0) - np.min(depths_smooth, axis=0)
                d_spread = np.diff(depth_spread)
                
                fig_debug = make_subplots(
                    rows=4, cols=1,
                    subplot_titles=("Smoothed Tension & Derivative", "Release Device Depth & Derivative", "All Depth Velocities", "Depth Spread"),
                    specs=[[{"secondary_y": True}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
                    vertical_spacing=0.08,
                    shared_xaxes=True
                )
                
                # Row 1: Tension
                fig_debug.add_trace(
                    go.Scatter(x=x_vals, y=tension, mode='lines', name='Raw Tension', 
                              line=dict(color='red', width=1, dash='dot'), opacity=0.5),
                    row=1, col=1, secondary_y=False
                )
                fig_debug.add_trace(
                    go.Scatter(x=x_vals, y=tension_smooth, mode='lines', name='Smoothed Tension', 
                              line=dict(color='darkred', width=2)),
                    row=1, col=1, secondary_y=False
                )
                fig_debug.add_trace(
                    go.Scatter(x=x_vals[:-1], y=d_tension, mode='lines', name='Tension Derivative', 
                              line=dict(color='purple', width=2)),
                    row=1, col=1, secondary_y=True
                )
                fig_debug.add_vline(x=winch_trip_idx, line_dash="dash", line_color="red", row=1, col=1)
                fig_debug.update_yaxes(title_text="Tension (lbs)", row=1, col=1, secondary_y=False)
                fig_debug.update_yaxes(title_text="dTension/dt", row=1, col=1, secondary_y=True)
                
                # Row 2: Release Device
                release_idx = 0
                fig_debug.add_trace(
                    go.Scatter(x=x_vals, y=depths[release_idx], mode='lines', name='Raw Sensor 0', 
                              line=dict(color='green', width=1, dash='dot'), opacity=0.5),
                    row=2, col=1, secondary_y=False
                )
                fig_debug.add_trace(
                    go.Scatter(x=x_vals, y=depths_smooth[release_idx], mode='lines', name='Smoothed Sensor 0', 
                              line=dict(color='darkgreen', width=2)),
                    row=2, col=1, secondary_y=False
                )
                fig_debug.add_trace(
                    go.Scatter(x=x_vals[:-1], y=d_depths[release_idx], mode='lines', name='Sensor 0 Derivative', 
                              line=dict(color='lime', width=2)),
                    row=2, col=1, secondary_y=True
                )
                fig_debug.add_hline(y=0, line_color="black", line_width=0.5, row=2, col=1, secondary_y=True)
                fig_debug.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", row=2, col=1)
                fig_debug.update_yaxes(title_text="Depth (m)", row=2, col=1, secondary_y=False, autorange="reversed")
                fig_debug.update_yaxes(title_text="dDepth/dt", row=2, col=1, secondary_y=True)
                
                # Row 3: All depth velocities
                for i, col in enumerate(depth_cols):
                    fig_debug.add_trace(
                        go.Scatter(x=x_vals[:-1], y=d_depths[i], mode='lines', name=f"{col[:30]} velocity", 
                                  line=dict(color=colors[i], width=1.5)),
                        row=3, col=1
                    )
                fig_debug.add_hline(y=0, line_color="black", line_width=0.5, row=3, col=1)
                fig_debug.add_vline(x=rbr_trip_idx, line_dash="dot", line_color="green", row=3, col=1)
                fig_debug.update_yaxes(title_text="Velocity (m/sample)", row=3, col=1)
                
                # Row 4: Depth spread
                fig_debug.add_trace(
                    go.Scatter(x=x_vals, y=depth_spread, mode='lines', name='Sensor Spread', 
                              line=dict(color='brown', width=2)),
                    row=4, col=1, secondary_y=False
                )
                fig_debug.add_trace(
                    go.Scatter(x=x_vals[:-1], y=d_spread, mode='lines', name='Spread Derivative', 
                              line=dict(color='darkred', width=2)),
                    row=4, col=1, secondary_y=True
                )
                fig_debug.update_xaxes(title_text="Sample index", row=4, col=1)
                fig_debug.update_yaxes(title_text="Spread (m)", row=4, col=1, secondary_y=False)
                fig_debug.update_yaxes(title_text="dSpread/dt", row=4, col=1, secondary_y=True)
                
                fig_debug.update_layout(height=1200, hovermode='x unified', showlegend=True)
                st.plotly_chart(fig_debug, use_container_width=True)
            
        except Exception as e:
            st.error(f"Error: {e}")
            import traceback
            st.write(traceback.format_exc())
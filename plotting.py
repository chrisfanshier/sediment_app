import plotly.graph_objects as go  # For creating plots
from plotly.subplots import make_subplots  # For creating subplots
import streamlit as st  # For rendering plots in the Streamlit app
import plotly.express as px
from utils import downsample_data
import pandas as pd
from config import get_full_path
import plotly.subplots as sp
import plotly.graph_objects as go

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

def plot_rbr_downsampled(primary_df, overlay_df=None, third_df=None, y_axis="Depth (m)", max_points=1000, primary_core_name="Primary Core"):
    """Generate a downsampled Plotly line plot for RBR primary, overlay, and third traces."""
    # Downsample primary data
    primary_downsampled_df = downsample_data(primary_df, max_points=max_points)

    # Autogenerate title
    title = f"{primary_core_name}: Downsampled Plot of {y_axis}"
    if overlay_df is not None or third_df is not None:
        title += " (with Overlay and/or Third Trace)"

    # Create the figure for the primary trace
    fig = px.line(
        primary_downsampled_df, x="Timestamp", y=y_axis,
        title=title,
        color_discrete_sequence=["blue"]
    )
    fig.data[0].name = "Primary"

    # Add overlay data if available
    if overlay_df is not None:
        overlay_downsampled_df = downsample_data(overlay_df, max_points=max_points)
        overlay_trace = px.line(
            overlay_downsampled_df, x="Timestamp", y=y_axis,
            color_discrete_sequence=["red"]
        ).data[0]
        overlay_trace.name = "Overlay"
        fig.add_trace(overlay_trace)

    # Add third trace data if available
    if third_df is not None:
        third_downsampled_df = downsample_data(third_df, max_points=max_points)
        third_trace = px.line(
            third_downsampled_df, x="Timestamp", y=y_axis,
            color_discrete_sequence=["green"]
        ).data[0]
        third_trace.name = "Third Trace"
        fig.add_trace(third_trace)

    # Check if y_axis is depth or pressure related - if so, invert y-axis
    depth_pressure_params = ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"]
    y_axis_reversed = y_axis in depth_pressure_params

    # Update layout with autogenerated legend
    fig.update_layout(
        showlegend=True,
        legend_title_text="Data Source",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        xaxis_title="Timestamp",
        yaxis_title=y_axis,
        template="plotly_white",
        yaxis=dict(autorange="reversed" if y_axis_reversed else True),
        height=600,
    )
    return fig

def plot_rbr_high_resolution(
    primary_df, overlay_df=None, third_df=None, y_axis="Depth (m)", start_time=None, end_time=None,
    primary_core_name="Primary Core", overlay_x_offset=0.0, overlay_y_offset=0.0,
    third_x_offset=0.0, third_y_offset=0.0
):
    """Generate a high-resolution Plotly line plot for RBR primary, overlay, and third traces with offsets."""
    # Filter primary data for the selected time range
    high_res_df = primary_df[
        (primary_df["Timestamp"] >= start_time) & (primary_df["Timestamp"] <= end_time)
    ]

    # Autogenerate title
    title = f"{primary_core_name}: High-Resolution Plot of {y_axis}"
    if overlay_df is not None or third_df is not None:
        title += " (with Overlay and/or Third Trace)"

    # Create the figure for the primary trace
    fig = px.line(
        high_res_df, x="Timestamp", y=y_axis,
        title=title,
        color_discrete_sequence=["blue"]
    )
    fig.data[0].name = "Primary"

    # Add overlay data if available
    if overlay_df is not None:
        overlay_high_res_df = overlay_df[
            (overlay_df["Timestamp"] >= start_time) & (overlay_df["Timestamp"] <= end_time)
        ].copy()  # Explicitly create a copy
        # Apply x and y offsets
        overlay_high_res_df["Timestamp"] += pd.to_timedelta(overlay_x_offset, unit="s")
        overlay_high_res_df[y_axis] += overlay_y_offset
        overlay_trace = px.line(
            overlay_high_res_df, x="Timestamp", y=y_axis,
            color_discrete_sequence=["red"]
        ).data[0]
        overlay_trace.name = "Overlay"
        fig.add_trace(overlay_trace)

    # Add third trace data if available
    if third_df is not None:
        third_high_res_df = third_df[
            (third_df["Timestamp"] >= start_time) & (third_df["Timestamp"] <= end_time)
        ].copy()  # Explicitly create a copy
        # Apply x and y offsets
        third_high_res_df["Timestamp"] += pd.to_timedelta(third_x_offset, unit="s")
        third_high_res_df[y_axis] += third_y_offset
        third_trace = px.line(
            third_high_res_df, x="Timestamp", y=y_axis,
            color_discrete_sequence=["green"]
        ).data[0]
        third_trace.name = "Third Trace"
        fig.add_trace(third_trace)

    # Check if y_axis is depth or pressure related - if so, invert y-axis
    depth_pressure_params = ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"]
    y_axis_reversed = y_axis in depth_pressure_params

    # Update layout with autogenerated legend
    fig.update_layout(
        showlegend=True,
        legend_title_text="Data Source",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        xaxis_title="Timestamp",
        yaxis_title=y_axis,
        template="plotly_white",
        yaxis=dict(autorange="reversed" if y_axis_reversed else True),
        height=600,
    )
    return fig

def plot_rbr_dual_simple(top_primary_df, top_overlay_df, top_third_df, top_y_axis,
                        lower_primary_df, lower_overlay_df, lower_third_df, lower_y_axis,
                        max_points=1000, top_name="Top Plot", lower_name="lower Plot",
                        top_metadata=None, lower_metadata=None):
    """Create simple dual stacked plot with separate file selections for top and lower"""
    
    # Create subplots with shared x-axis - cleaner titles without "Top" and "lower"
    fig = sp.make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(f"{top_name}: {top_y_axis}", f"{lower_name}: {lower_y_axis}"),
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Downsample function
    def downsample_data_local(df, max_points):
        if len(df) <= max_points:
            return df
        step = len(df) // max_points
        return df.iloc[::step]
    
    # Helper function to create legend name
    def create_legend_name(core_name, sensor_location, trace_type="Primary"):
        if sensor_location:
            return f"{core_name} - {sensor_location}"
        else:
            return f"{core_name} - {trace_type}"
    
    # Add top plot traces
    if top_primary_df is not None and top_y_axis in top_primary_df.columns:
        top_primary_downsampled = downsample_data_local(top_primary_df, max_points)
        legend_name = create_legend_name(
            top_name, 
            top_metadata.get('primary_sensor_location') if top_metadata else None,
            "Primary"
        )
        fig.add_trace(
            go.Scatter(x=top_primary_downsampled["Timestamp"], y=top_primary_downsampled[top_y_axis],
                      mode='lines', name=legend_name, line=dict(color='blue')),
            row=1, col=1
        )
    
    if top_overlay_df is not None and top_y_axis in top_overlay_df.columns:
        top_overlay_downsampled = downsample_data_local(top_overlay_df, max_points)
        legend_name = create_legend_name(
            top_metadata.get('overlay_core_name', top_name) if top_metadata else top_name,
            top_metadata.get('overlay_sensor_location') if top_metadata else None,
            "Overlay"
        )
        fig.add_trace(
            go.Scatter(x=top_overlay_downsampled["Timestamp"], y=top_overlay_downsampled[top_y_axis],
                      mode='lines', name=legend_name, line=dict(color='red')),
            row=1, col=1
        )
    
    if top_third_df is not None and top_y_axis in top_third_df.columns:
        top_third_downsampled = downsample_data_local(top_third_df, max_points)
        legend_name = create_legend_name(
            top_metadata.get('third_core_name', top_name) if top_metadata else top_name,
            top_metadata.get('third_sensor_location') if top_metadata else None,
            "Third"
        )
        fig.add_trace(
            go.Scatter(x=top_third_downsampled["Timestamp"], y=top_third_downsampled[top_y_axis],
                      mode='lines', name=legend_name, line=dict(color='green')),
            row=1, col=1
        )
    
    # Add lower plot traces
    if lower_primary_df is not None and lower_y_axis in lower_primary_df.columns:
        lower_primary_downsampled = downsample_data_local(lower_primary_df, max_points)
        legend_name = create_legend_name(
            lower_name,
            lower_metadata.get('primary_sensor_location') if lower_metadata else None,
            "Primary"
        )
        fig.add_trace(
            go.Scatter(x=lower_primary_downsampled["Timestamp"], y=lower_primary_downsampled[lower_y_axis],
                      mode='lines', name=legend_name, line=dict(color='blue', dash='dot')),
            row=2, col=1
        )
    
    if lower_overlay_df is not None and lower_y_axis in lower_overlay_df.columns:
        lower_overlay_downsampled = downsample_data_local(lower_overlay_df, max_points)
        legend_name = create_legend_name(
            lower_metadata.get('overlay_core_name', lower_name) if lower_metadata else lower_name,
            lower_metadata.get('overlay_sensor_location') if lower_metadata else None,
            "Overlay"
        )
        fig.add_trace(
            go.Scatter(x=lower_overlay_downsampled["Timestamp"], y=lower_overlay_downsampled[lower_y_axis],
                      mode='lines', name=legend_name, line=dict(color='red', dash='dot')),
            row=2, col=1
        )
    
    if lower_third_df is not None and lower_y_axis in lower_third_df.columns:
        lower_third_downsampled = downsample_data_local(lower_third_df, max_points)
        legend_name = create_legend_name(
            lower_metadata.get('third_core_name', lower_name) if lower_metadata else lower_name,
            lower_metadata.get('third_sensor_location') if lower_metadata else None,
            "Third"
        )
        fig.add_trace(
            go.Scatter(x=lower_third_downsampled["Timestamp"], y=lower_third_downsampled[lower_y_axis],
                      mode='lines', name=legend_name, line=dict(color='green', dash='dot')),
            row=2, col=1
        )
    
    # Check if parameters are depth/pressure related for y-axis inversion
    depth_pressure_params = ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"]
    top_y_reversed = top_y_axis in depth_pressure_params
    lower_y_reversed = lower_y_axis in depth_pressure_params
    
    # Update layout
    fig.update_layout(height=800, showlegend=True, title="Dual Parameter Time Series")
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text=top_y_axis, row=1, col=1, autorange="reversed" if top_y_reversed else True)
    fig.update_yaxes(title_text=lower_y_axis, row=2, col=1, autorange="reversed" if lower_y_reversed else True)
    
    return fig

def plot_rbr_dual_simple_high_res(top_primary_df, top_overlay_df, top_third_df, top_y_axis,
                                 lower_primary_df, lower_overlay_df, lower_third_df, lower_y_axis,
                                 start_time=None, end_time=None,
                                 top_name="Top Plot", lower_name="lower Plot",
                                 top_metadata=None, lower_metadata=None):
    """Create high-resolution dual stacked plot"""
    import plotly.subplots as sp
    import plotly.graph_objects as go
    import pandas as pd
    
    # Parse time range
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    
    # Create subplots with shared x-axis - cleaner titles
    fig = sp.make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(f"{top_name}: {top_y_axis} (High Resolution)", 
                       f"{lower_name}: {lower_y_axis} (High Resolution)"),
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Helper function to create legend name
    def create_legend_name(core_name, sensor_location, trace_type="Primary"):
        if sensor_location:
            return f"{core_name} - {sensor_location}"
        else:
            return f"{core_name} - {trace_type}"
    
    # Add top plot traces with time filtering
    trace_configs = [
        (top_primary_df, "primary", 'blue', 'solid'),
        (top_overlay_df, "overlay", 'red', 'solid'),
        (top_third_df, "third", 'green', 'solid')
    ]
    
    for df, trace_type, color, style in trace_configs:
        if df is not None and top_y_axis in df.columns:
            filtered_df = df[(df["Timestamp"] >= start_dt) & (df["Timestamp"] <= end_dt)]
            if not filtered_df.empty:
                # Get metadata for this trace
                if trace_type == "primary":
                    core_name = top_name
                    sensor_location = top_metadata.get('primary_sensor_location') if top_metadata else None
                elif trace_type == "overlay":
                    core_name = top_metadata.get('overlay_core_name', top_name) if top_metadata else top_name
                    sensor_location = top_metadata.get('overlay_sensor_location') if top_metadata else None
                else:  # third
                    core_name = top_metadata.get('third_core_name', top_name) if top_metadata else top_name
                    sensor_location = top_metadata.get('third_sensor_location') if top_metadata else None
                
                legend_name = create_legend_name(core_name, sensor_location, trace_type.title())
                
                fig.add_trace(
                    go.Scatter(x=filtered_df["Timestamp"], y=filtered_df[top_y_axis],
                              mode='lines+markers', name=legend_name, 
                              line=dict(color=color, dash=style),
                              marker=dict(size=2)),
                    row=1, col=1
                )
    
    # Add lower plot traces with time filtering
    lower_trace_configs = [
        (lower_primary_df, "primary", 'blue', 'dot'),
        (lower_overlay_df, "overlay", 'red', 'dot'),
        (lower_third_df, "third", 'green', 'dot')
    ]
    
    for df, trace_type, color, style in lower_trace_configs:
        if df is not None and lower_y_axis in df.columns:
            filtered_df = df[(df["Timestamp"] >= start_dt) & (df["Timestamp"] <= end_dt)]
            if not filtered_df.empty:
                # Get metadata for this trace
                if trace_type == "primary":
                    core_name = lower_name
                    sensor_location = lower_metadata.get('primary_sensor_location') if lower_metadata else None
                elif trace_type == "overlay":
                    core_name = lower_metadata.get('overlay_core_name', lower_name) if lower_metadata else lower_name
                    sensor_location = lower_metadata.get('overlay_sensor_location') if lower_metadata else None
                else:  # third
                    core_name = lower_metadata.get('third_core_name', lower_name) if lower_metadata else lower_name
                    sensor_location = lower_metadata.get('third_sensor_location') if lower_metadata else None
                
                legend_name = create_legend_name(core_name, sensor_location, trace_type.title())
                
                fig.add_trace(
                    go.Scatter(x=filtered_df["Timestamp"], y=filtered_df[lower_y_axis],
                              mode='lines+markers', name=legend_name, 
                              line=dict(color=color, dash=style),
                              marker=dict(size=2)),
                    row=2, col=1
                )
    
    # Check if parameters are depth/pressure related for y-axis inversion
    depth_pressure_params = ["Depth (m)", "Pressure (dbar)", "Sea Pressure (dbar)"]
    top_y_reversed = top_y_axis in depth_pressure_params
    lower_y_reversed = lower_y_axis in depth_pressure_params
    
    # Update layout
    fig.update_layout(
        height=800, 
        showlegend=True,
        title=f"High-Resolution Dual Plot: {start_time} to {end_time}"
    )
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text=top_y_axis, row=1, col=1, autorange="reversed" if top_y_reversed else True)
    fig.update_yaxes(title_text=lower_y_axis, row=2, col=1, autorange="reversed" if lower_y_reversed else True)
    
    return fig
import plotly.graph_objects as go  # For creating plots
from plotly.subplots import make_subplots  # For creating subplots
import streamlit as st  # For rendering plots in the Streamlit app
import plotly.express as px
from utils import downsample_data
import pandas as pd
from config import get_full_path

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

    # Update layout with autogenerated legend
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

    # Update layout with autogenerated legend
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
    return fig

def plot_rbr_dual_stacked(primary_df, overlay_df=None, third_df=None, 
                         y_axis_1="Depth (m)", y_axis_2="Tilt X",
                         max_points=1000, primary_core_name="Primary Core",
                         overlay_x_offset=0, overlay_y_offset=0,
                         third_x_offset=0, third_y_offset=0):
    """Create vertically stacked subplots with different parameters sharing time axis"""
    import plotly.subplots as sp
    import plotly.graph_objects as go
    
    # Create subplots with shared x-axis
    fig = sp.make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(f'{y_axis_1}', f'{y_axis_2}'),
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Downsample data for performance
    def downsample_data(df, max_points):
        if len(df) <= max_points:
            return df
        step = len(df) // max_points
        return df.iloc[::step]
    
    primary_downsampled = downsample_data(primary_df, max_points)
    
    # Add primary traces
    fig.add_trace(
        go.Scatter(
            x=primary_downsampled["Timestamp"], 
            y=primary_downsampled[y_axis_1],
            mode='lines', 
            name=f'{primary_core_name} - {y_axis_1}',
            line=dict(color='blue')
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=primary_downsampled["Timestamp"], 
            y=primary_downsampled[y_axis_2],
            mode='lines', 
            name=f'{primary_core_name} - {y_axis_2}',
            line=dict(color='blue')
        ),
        row=2, col=1
    )
    
    # Add overlay traces if available
    if overlay_df is not None:
        overlay_downsampled = downsample_data(overlay_df, max_points)
        
        # Apply offsets
        overlay_x_adjusted = overlay_downsampled["Timestamp"] + pd.Timedelta(seconds=overlay_x_offset)
        
        if y_axis_1 in overlay_downsampled.columns:
            overlay_y1_adjusted = overlay_downsampled[y_axis_1] + overlay_y_offset
            fig.add_trace(
                go.Scatter(
                    x=overlay_x_adjusted,
                    y=overlay_y1_adjusted,
                    mode='lines',
                    name=f'Overlay - {y_axis_1}',
                    line=dict(color='red')
                ),
                row=1, col=1
            )
        
        if y_axis_2 in overlay_downsampled.columns:
            overlay_y2_adjusted = overlay_downsampled[y_axis_2] + overlay_y_offset
            fig.add_trace(
                go.Scatter(
                    x=overlay_x_adjusted,
                    y=overlay_y2_adjusted,
                    mode='lines',
                    name=f'Overlay - {y_axis_2}',
                    line=dict(color='red')
                ),
                row=2, col=1
            )
    
    # Add third traces if available
    if third_df is not None:
        third_downsampled = downsample_data(third_df, max_points)
        
        # Apply offsets
        third_x_adjusted = third_downsampled["Timestamp"] + pd.Timedelta(seconds=third_x_offset)
        
        if y_axis_1 in third_downsampled.columns:
            third_y1_adjusted = third_downsampled[y_axis_1] + third_y_offset
            fig.add_trace(
                go.Scatter(
                    x=third_x_adjusted,
                    y=third_y1_adjusted,
                    mode='lines',
                    name=f'Third - {y_axis_1}',
                    line=dict(color='green')
                ),
                row=1, col=1
            )
        
        if y_axis_2 in third_downsampled.columns:
            third_y2_adjusted = third_downsampled[y_axis_2] + third_y_offset
            fig.add_trace(
                go.Scatter(
                    x=third_x_adjusted,
                    y=third_y2_adjusted,
                    mode='lines',
                    name=f'Third - {y_axis_2}',
                    line=dict(color='green')
                ),
                row=2, col=1
            )
    
    # Update layout
    fig.update_layout(
        height=800, 
        showlegend=True,
        title="Dual Parameter Time Series Comparison"
    )
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text=y_axis_1, row=1, col=1)
    fig.update_yaxes(title_text=y_axis_2, row=2, col=1)
    
    return fig

def plot_rbr_dual_stacked_flexible(param1_df, param2_df, 
                                  y_axis_1="Depth (m)", y_axis_2="Tilt X",
                                  max_points=1000, 
                                  param1_name="Parameter 1", param2_name="Parameter 2"):
    """Create vertically stacked subplots with different parameters from potentially different DataFrames"""
    import plotly.subplots as sp
    import plotly.graph_objects as go
    
    # Create subplots with shared x-axis
    fig = sp.make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(param1_name, param2_name),
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Downsample data for performance
    def downsample_data(df, max_points):
        if len(df) <= max_points:
            return df
        step = len(df) // max_points
        return df.iloc[::step]
    
    # Process first parameter
    if param1_df is not None and y_axis_1 in param1_df.columns:
        param1_downsampled = downsample_data(param1_df, max_points)
        fig.add_trace(
            go.Scatter(
                x=param1_downsampled["Timestamp"], 
                y=param1_downsampled[y_axis_1],
                mode='lines', 
                name=param1_name,
                line=dict(color='blue')
            ),
            row=1, col=1
        )
    
    # Process second parameter
    if param2_df is not None and y_axis_2 in param2_df.columns:
        param2_downsampled = downsample_data(param2_df, max_points)
        fig.add_trace(
            go.Scatter(
                x=param2_downsampled["Timestamp"], 
                y=param2_downsampled[y_axis_2],
                mode='lines', 
                name=param2_name,
                line=dict(color='red')
            ),
            row=2, col=1
        )
    
    # Update layout
    fig.update_layout(
        height=800, 
        showlegend=True,
        title="Dual Parameter Time Series Comparison"
    )
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text=y_axis_1, row=1, col=1)
    fig.update_yaxes(title_text=y_axis_2, row=2, col=1)
    
    return fig

def plot_rbr_dual_high_resolution(param1_df, param2_df, 
                                 y_axis_1="Depth (m)", y_axis_2="Tilt X",
                                 start_time=None, end_time=None,
                                 param1_name="Parameter 1", param2_name="Parameter 2"):
    """Create high-resolution vertically stacked subplots for specified time range"""
    import plotly.subplots as sp
    import plotly.graph_objects as go
    import pandas as pd
    
    # Parse time range
    start_dt = pd.to_datetime(start_time)
    end_dt = pd.to_datetime(end_time)
    
    # Create subplots with shared x-axis
    fig = sp.make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(f"{param1_name} (High Resolution)", f"{param2_name} (High Resolution)"),
        vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    # Filter and plot first parameter
    if param1_df is not None and y_axis_1 in param1_df.columns:
        param1_filtered = param1_df[
            (param1_df["Timestamp"] >= start_dt) & 
            (param1_df["Timestamp"] <= end_dt)
        ]
        
        fig.add_trace(
            go.Scatter(
                x=param1_filtered["Timestamp"], 
                y=param1_filtered[y_axis_1],
                mode='lines+markers', 
                name=param1_name,
                line=dict(color='blue'),
                marker=dict(size=2)
            ),
            row=1, col=1
        )
    
    # Filter and plot second parameter
    if param2_df is not None and y_axis_2 in param2_df.columns:
        param2_filtered = param2_df[
            (param2_df["Timestamp"] >= start_dt) & 
            (param2_df["Timestamp"] <= end_dt)
        ]
        
        fig.add_trace(
            go.Scatter(
                x=param2_filtered["Timestamp"], 
                y=param2_filtered[y_axis_2],
                mode='lines+markers', 
                name=param2_name,
                line=dict(color='red'),
                marker=dict(size=2)
            ),
            row=2, col=1
        )
    
    # Update layout
    fig.update_layout(
        height=800, 
        showlegend=True,
        title=f"High-Resolution Dual Plot: {start_time} to {end_time}"
    )
    fig.update_xaxes(title_text="Time", row=2, col=1)
    fig.update_yaxes(title_text=y_axis_1, row=1, col=1)
    fig.update_yaxes(title_text=y_axis_2, row=2, col=1)
    
    return fig
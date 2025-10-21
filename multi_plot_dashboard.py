import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=FutureWarning, module='pandas')
warnings.filterwarnings('ignore', message='.*day of month without a year.*')

import dash
from dash import dcc, html, Input, Output, State, callback
from dash import callback_context  # Add this line
import plotly.graph_objects as go
import pandas as pd
import os
from db_util import get_connection, fetch_cruise_options
from sqlalchemy import text
from utils import process_rsk_data, process_star_oddi_data

app = dash.Dash(__name__)
app.title = "Sensor Data Plotter"

def load_sensor_data(sensor_file_id):
    """Load sensor data from database and file"""
    with get_connection() as conn:
        query = text("""
            SELECT sf.*, c.core_name 
            FROM sensor_files sf 
            JOIN cores c ON sf.core_id = c.core_id 
            WHERE sf.file_id = :file_id
        """)
        sensor_info = conn.execute(query, {"file_id": sensor_file_id}).fetchone()
    
    if not sensor_info:
        return None, None
    
    relative_path = os.path.join(sensor_info.file_path, sensor_info.file_name)
    file_ext = os.path.splitext(sensor_info.file_name)[1].lower()
    sensor_type = sensor_info.sensor_type.lower() if sensor_info.sensor_type else ""
    
    try:
        if file_ext == '.rsk' or 'rbr' in sensor_type:
            df = process_rsk_data(relative_path)
        elif file_ext in ['.dat', '.acc'] or 'star-oddi' in sensor_type or 'staroddi' in sensor_type:
            df = process_star_oddi_data(relative_path)
        else:
            return None, None

        if df is not None:
            if 'datetime' not in df.columns:
                if 'Timestamp' in df.columns:
                    df['datetime'] = df['Timestamp']
                else:
                    df['datetime'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1s')
            return df, sensor_info
        else:
            return None, None
    except Exception as e:
        print(f"Error loading sensor data: {e}")
        return None, None

# App layout
app.layout = html.Div([
    html.Div([
        html.H1("🌡️ Sensor Data Plotter", style={'textAlign': 'center', 'color': '#2c3e50'}),
        html.P("Overlay multiple sensor measurements with winch data", style={'textAlign': 'center', 'color': '#7f8c8d'})
    ], style={'backgroundColor': '#ecf0f1', 'padding': '20px', 'marginBottom': '20px'}),
    
    # Main Control Panel
    html.Div([
        html.Div([
            html.Label("Select Cruise:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='cruise-dropdown', placeholder="Choose a cruise...")
        ], style={'width': '20%'}),
        
        html.Div([
            html.Label("Select Core:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='core-dropdown', placeholder="Choose a core...")
        ], style={'width': '20%'}),
        
        html.Div([
            html.Label("Select Sensor Files:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(id='sensor-files-dropdown', multi=True, placeholder="Choose sensor files...")
        ], style={'width': '28%'}),
        
        html.Div([
            html.Label("Select Parameter:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='parameter-dropdown', 
                placeholder="Choose parameter to plot...",
                options=[
                    {'label': 'Temperature', 'value': 'temperature'},
                    {'label': 'Pressure', 'value': 'pressure'},
                    {'label': 'Conductivity', 'value': 'conductivity'},
                    {'label': 'Salinity', 'value': 'salinity'},
                    {'label': 'All Available', 'value': 'all'}
                ],
                value='temperature'  # Default selection
            )
        ], style={'width': '30%'})
    ], style={
        'display': 'flex', 
        'gap': '1%', 
        'backgroundColor': '#f8f9fa', 
        'padding': '20px', 
        'borderRadius': '10px', 
        'marginBottom': '10px'
    }),
    
    # Additional Trace Panel
    html.Div([
        html.Div([
            html.Label("Add Companion Core:", style={'fontWeight': 'bold', 'color': '#e67e22'}),
            dcc.Dropdown(id='companion-core-dropdown', placeholder="Choose companion core (e.g., TC for JC)...")
        ], style={'width': '30%'}),
        
        html.Div([
            html.Label("Companion Sensor Files:", style={'fontWeight': 'bold', 'color': '#e67e22'}),
            dcc.Dropdown(id='companion-files-dropdown', multi=True, placeholder="Choose companion sensor files...")
        ], style={'width': '68%'})
    ], style={
        'display': 'flex', 
        'gap': '1%', 
        'backgroundColor': '#fdf2e9', 
        'padding': '15px', 
        'borderRadius': '10px', 
        'marginBottom': '10px',
        'border': '2px dashed #e67e22'
    }),
    
    # Winch Data Panel
    html.Div([
        html.Div([
            html.Label("Select Winch Data File:", style={'fontWeight': 'bold', 'color': '#8e44ad'}),
            dcc.Dropdown(id='winch-files-dropdown', placeholder="Choose winch data file...")
        ], style={'width': '40%'}),
        
        html.Div([
            html.Label("Winch Parameter:", style={'fontWeight': 'bold', 'color': '#8e44ad'}),
            dcc.Dropdown(id='winch-parameter-dropdown', placeholder="Choose winch parameter...")
        ], style={'width': '30%'}),
        
        html.Div([
            html.Label("Show Winch Data:", style={'fontWeight': 'bold', 'color': '#8e44ad'}),
            dcc.Checklist(
                id='winch-enabled-checkbox',
                options=[{'label': ' Enable Winch Plot', 'value': 'enabled'}],
                value=[],
                style={'marginTop': '5px'}
            )
        ], style={'width': '28%'})
    ], style={
        'display': 'flex', 
        'gap': '1%', 
        'backgroundColor': '#f4f1f8', 
        'padding': '15px', 
        'borderRadius': '10px', 
        'marginBottom': '20px',
        'border': '2px dashed #8e44ad'
    }),
    
    # Time range slider
    dcc.RangeSlider(
        id='time-range-slider',
        min=0, max=100, step=1, value=[0, 100], marks={},
        tooltip={"placement": "bottom", "always_visible": True}
    ),
    
    # Detail mode button
    html.Div([
        html.Button("🔍 Show All Points in Current View", id="detail-mode-btn", n_clicks=0,
                   style={'backgroundColor': '#3498db', 'color': 'white', 'border': 'none', 
                          'padding': '10px 20px', 'borderRadius': '5px', 'cursor': 'pointer'}),
        html.Span(id="mode-indicator", children="Overview Mode Active", 
                 style={'marginLeft': '20px', 'fontWeight': 'bold'})
    ], style={'textAlign': 'center', 'marginBottom': '20px'}),
    
    # Single Subplot Figure with Shared X-Axis
    dcc.Graph(
        id='combined-plot',
        config={
            'displayModeBar': True, 
            'displaylogo': False, 
            'doubleClick': 'reset',
            'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape']
        },
        style={'height': '600px', 'marginBottom': '20px'}
    ),
    
    # Data info
    html.Div(id='data-info', style={'marginTop': '20px'}),
    
    # Store for available parameters
    dcc.Store(id='available-parameters-store', data=[])
])

# Callbacks
@callback(Output('cruise-dropdown', 'options'), Input('cruise-dropdown', 'id'))
def load_cruise_options(_):
    cruises = fetch_cruise_options()
    return [{'label': f"{cruise.cruise_name} - {cruise.vessel_name}", 'value': cruise.cruise_id} 
            for cruise in cruises]

@callback(Output('core-dropdown', 'options'), Input('cruise-dropdown', 'value'))
def load_cores(cruise_id):
    if not cruise_id:
        return []
    with get_connection() as conn:
        query = text("SELECT core_id, core_name FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name")
        cores = pd.read_sql(query, conn, params={"cruise_id": cruise_id})
    return [{'label': row['core_name'], 'value': row['core_id']} for _, row in cores.iterrows()]

@callback(Output('sensor-files-dropdown', 'options'), Input('core-dropdown', 'value'))
def load_sensor_files(core_id):
    if not core_id:
        return []
    with get_connection() as conn:
        query = text("""
            SELECT file_id, file_name, sensor_type, sensor_location 
            FROM sensor_files WHERE core_id = :core_id ORDER BY file_name
        """)
        sensor_files = pd.read_sql(query, conn, params={"core_id": core_id})
    return [{'label': f"{row['file_name']} ({row['sensor_type']} - {row['sensor_location']})", 
             'value': row['file_id']} for _, row in sensor_files.iterrows()]

@callback(
    [Output('time-range-slider', 'min'), Output('time-range-slider', 'max'), 
     Output('time-range-slider', 'value'), Output('time-range-slider', 'marks')],
    Input('sensor-files-dropdown', 'value')
)
def update_time_slider(selected_sensor_files):
    if not selected_sensor_files:
        return 0, 100, [0, 100], {}
    
    min_time, max_time = None, None
    for file_id in selected_sensor_files:
        df, info = load_sensor_data(file_id)
        if df is not None and 'datetime' in df.columns:
            dt_min, dt_max = df['datetime'].min(), df['datetime'].max()
            if min_time is None or dt_min < min_time:
                min_time = dt_min
            if max_time is None or dt_max > max_time:
                max_time = dt_max
    
    if min_time is None or max_time is None:
        return 0, 100, [0, 100], {}
    
    min_ts, max_ts = int(min_time.timestamp()), int(max_time.timestamp())
    step = max(1, (max_ts - min_ts) // 4)
    marks = {ts: pd.to_datetime(ts, unit='s').strftime('%Y-%m-%d %H:%M') 
             for ts in range(min_ts, max_ts + 1, step)}
    marks[min_ts] = min_time.strftime('%Y-%m-%d %H:%M')
    marks[max_ts] = max_time.strftime('%Y-%m-%d %H:%M')
    
    return min_ts, max_ts, [min_ts, max_ts], marks

@callback(
    [Output('parameter-dropdown', 'options'), Output('parameter-dropdown', 'value')],
    Input('sensor-files-dropdown', 'value')
)
def update_parameter_options(selected_sensor_files):
    if not selected_sensor_files:
        return [{'label': 'Select sensor files first', 'value': 'none'}], 'none'
    
    # Collect all available parameters from selected files
    all_parameters = set()
    
    for file_id in selected_sensor_files:
        df, info = load_sensor_data(file_id)
        if df is not None:
            numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                           if col.lower() not in ['id', 'index']]
            
            for col in numeric_cols:
                all_parameters.add(col)
                print(f"[DEBUG] Found parameter '{col}' in {info.file_name if info else 'unknown file'}")
    
    if not all_parameters:
        return [{'label': 'No numeric parameters found', 'value': 'none'}], None
    
    # Create options from actual available parameters
    options = []
    
    # Add "All Available" option first
    options.append({'label': '📊 All Available Parameters', 'value': 'all'})
    
    # Group parameters by common types with icons
    temp_params = [p for p in all_parameters if any(term in p.lower() for term in ['temp', 'temperature'])]
    pressure_params = [p for p in all_parameters if any(term in p.lower() for term in ['press', 'pressure'])]
    depth_params = [p for p in all_parameters if any(term in p.lower() for term in ['depth'])]
    cond_params = [p for p in all_parameters if any(term in p.lower() for term in ['cond', 'conductivity'])]
    sal_params = [p for p in all_parameters if any(term in p.lower() for term in ['sal', 'salinity'])]
    other_params = [p for p in all_parameters if p not in temp_params + pressure_params + depth_params + cond_params + sal_params]
    
    # Add grouped parameters with icons
    if temp_params:
        for param in sorted(temp_params):
            options.append({'label': f"🌡️ {param}", 'value': param})
    
    if pressure_params:
        for param in sorted(pressure_params):
            options.append({'label': f"📊 {param}", 'value': param})
    
    if depth_params:
        for param in sorted(depth_params):
            options.append({'label': f"🌊 {param}", 'value': param})
    
    if cond_params:
        for param in sorted(cond_params):
            options.append({'label': f"⚡ {param}", 'value': param})
    
    if sal_params:
        for param in sorted(sal_params):
            options.append({'label': f"🧂 {param}", 'value': param})
    
    if other_params:
        for param in sorted(other_params):
            options.append({'label': f"📈 {param}", 'value': param})
    
    # Default to first temperature parameter, or first parameter, or 'all'
    if temp_params:
        default_value = sorted(temp_params)[0]
    elif all_parameters:
        default_value = sorted(list(all_parameters))[0]
    else:
        default_value = 'all'
    
    print(f"[DEBUG] Available parameters: {sorted(list(all_parameters))}")
    print(f"[DEBUG] Default parameter: {default_value}")
    
    return options, default_value

@callback(
    Output('companion-core-dropdown', 'options'), 
    [Input('cruise-dropdown', 'value'), Input('core-dropdown', 'value')]
)
def load_companion_cores(cruise_id, selected_core_id):
    if not cruise_id or not selected_core_id:
        return []
    
    with get_connection() as conn:
        # Get the selected core name to find companion
        selected_core_query = text("SELECT core_name FROM cores WHERE core_id = :core_id")
        selected_core = conn.execute(selected_core_query, {"core_id": selected_core_id}).fetchone()
        
        if not selected_core:
            return []
        
        selected_core_name = selected_core.core_name
        print(f"[DEBUG] Selected core: {selected_core_name}")
        
        # Look for companion cores (e.g., JC -> TC, TC -> JC)
        companion_options = []
        
        # If selected core is JC, look for TC (and vice versa)
        if 'JC' in selected_core_name:
            companion_pattern = selected_core_name.replace('JC', 'TC')
        elif 'TC' in selected_core_name:
            companion_pattern = selected_core_name.replace('TC', 'JC')
        else:
            # For other patterns, just get all other cores from same cruise
            companion_pattern = None
        
        # Get all cores from the same cruise
        all_cores_query = text("SELECT core_id, core_name FROM cores WHERE cruise_id = :cruise_id AND core_id != :selected_id ORDER BY core_name")
        all_cores = pd.read_sql(all_cores_query, conn, params={"cruise_id": cruise_id, "selected_id": selected_core_id})
        
        for _, row in all_cores.iterrows():
            core_name = row['core_name']
            if companion_pattern and companion_pattern in core_name:
                # Exact companion match (e.g., JC01 -> TC01)
                companion_options.append({
                    'label': f"🔗 {core_name} (Companion)", 
                    'value': row['core_id']
                })
            else:
                # Other available cores
                companion_options.append({
                    'label': f"📊 {core_name}", 
                    'value': row['core_id']
                })
        
        print(f"[DEBUG] Found {len(companion_options)} companion core options")
        return companion_options

@callback(
    Output('companion-files-dropdown', 'options'), 
    Input('companion-core-dropdown', 'value')
)
def load_companion_sensor_files(companion_core_id):
    if not companion_core_id:
        return []
    
    with get_connection() as conn:
        query = text("""
            SELECT file_id, file_name, sensor_type, sensor_location 
            FROM sensor_files WHERE core_id = :core_id ORDER BY file_name
        """)
        sensor_files = pd.read_sql(query, conn, params={"core_id": companion_core_id})
    
    return [{'label': f"{row['file_name']} ({row['sensor_type']} - {row['sensor_location']})", 
             'value': row['file_id']} for _, row in sensor_files.iterrows()]

@callback(
    Output('winch-files-dropdown', 'options'),
    [Input('cruise-dropdown', 'value'), Input('sensor-files-dropdown', 'value')]
)
def load_winch_files(cruise_id, selected_sensor_files):
    if not cruise_id:
        return []
    
    # Get sensor data time range for overlap suggestions
    sensor_start, sensor_end = None, None
    if selected_sensor_files:
        for file_id in selected_sensor_files:
            df, info = load_sensor_data(file_id)
            if df is not None and 'datetime' in df.columns:
                dt_min, dt_max = df['datetime'].min(), df['datetime'].max()
                if sensor_start is None or dt_min < sensor_start:
                    sensor_start = dt_min
                if sensor_end is None or dt_max > sensor_end:
                    sensor_end = dt_max
    
    with get_connection() as conn:
        # Get winch data files from the winch_data table - FIXED COLUMN NAMES
        query = text("""
            SELECT winch_file_id, file_path, file_name, start_time, end_time, notes, settings
            FROM winch_data 
            WHERE cruise_id = :cruise_id 
            ORDER BY start_time, file_name
        """)
        winch_files = pd.read_sql(query, conn, params={"cruise_id": cruise_id})
    
    if winch_files.empty:
        return [{'label': 'No winch files found for this cruise', 'value': 'none'}]
    
    options = []
    
    for _, row in winch_files.iterrows():
        # Convert start/end times to pandas datetime for comparison
        winch_start = pd.to_datetime(row['start_time']) if row['start_time'] else None
        winch_end = pd.to_datetime(row['end_time']) if row['end_time'] else None
        
        # Check for time overlap with sensor data
        overlap = False
        overlap_type = ""
        
        if sensor_start and sensor_end and winch_start and winch_end:
            # Check if there's any overlap between sensor and winch time ranges
            if not (sensor_end < winch_start or sensor_start > winch_end):
                overlap = True
                # Determine type of overlap
                if winch_start <= sensor_start and winch_end >= sensor_end:
                    overlap_type = " (Full Coverage)"
                elif sensor_start <= winch_start and sensor_end >= winch_end:
                    overlap_type = " (Partial Coverage)"
                else:
                    overlap_type = " (Overlap)"
        
        # Format the label with overlap indication
        if overlap:
            icon = "🎯"  # Target icon for overlapping files
            priority_label = f"{icon} {row['file_name']}{overlap_type}"
        else:
            icon = "🔧"  # Regular winch icon
            priority_label = f"{icon} {row['file_name']}"
        
        # Add timing info if available
        if winch_start and winch_end:
            time_info = f" [{winch_start.strftime('%m/%d %H:%M')} - {winch_end.strftime('%m/%d %H:%M')}]"
            priority_label += time_info
        
        # Add notes if available (changed from description to notes)
        if row['notes'] and pd.notna(row['notes']) and str(row['notes']).strip():
            priority_label += f" - {row['notes']}"
        
        options.append({
            'label': priority_label,
            'value': row['winch_file_id'],
            'overlap': overlap
        })
    
    # Sort options: overlapping files first, then by start time
    options.sort(key=lambda x: (not x.get('overlap', False), x['label']))
    
    # Remove the overlap key from options (not needed in dropdown)
    for option in options:
        option.pop('overlap', None)
    
    print(f"[DEBUG] Found {len(options)} winch files for cruise {cruise_id}")
    if sensor_start and sensor_end:
        print(f"[DEBUG] Sensor data range: {sensor_start} to {sensor_end}")
        overlapping_count = sum(1 for _, row in winch_files.iterrows() 
                               if row['start_time'] and row['end_time'] and 
                               not (sensor_end < pd.to_datetime(row['start_time']) or 
                                    sensor_start > pd.to_datetime(row['end_time'])))
        print(f"[DEBUG] {overlapping_count} winch files overlap with sensor data")
    
    return options

@callback(
    [Output('winch-parameter-dropdown', 'options'), Output('winch-parameter-dropdown', 'value')],
    Input('winch-files-dropdown', 'value')
)
def update_winch_parameters(winch_file_id):  # Changed from winch_id to winch_file_id
    if not winch_file_id or winch_file_id == 'none':
        return [], None
    
    try:
        # Load the winch data to see available parameters
        from utils import parse_winch_dat
        import json
        import os
        
        # Get file info from winch_data table
        with get_connection() as conn:
            query = text("SELECT file_name, file_path, settings FROM winch_data WHERE winch_file_id = :winch_file_id")
            file_info = conn.execute(query, {"winch_file_id": winch_file_id}).fetchone()
        
        if not file_info:
            return [{'label': 'Winch file not found in database', 'value': 'error'}], None
        
        # Parse the JSON settings
        try:
            settings = json.loads(file_info.settings) if file_info.settings else {}
            print(f"[DEBUG] Parsed winch settings: {settings}")
        except json.JSONDecodeError as e:
            print(f"[DEBUG] Error parsing JSON settings: {e}")
            settings = {}
        
        # Construct full file path
        full_file_path = os.path.join(file_info.file_path, file_info.file_name)
        print(f"[DEBUG] Loading winch file: {full_file_path}")
        
        # Use the settings from the database or create basic fallback
        if settings:
            # Use the stored settings from the database
            parsing_settings = {
                "delimiter": settings.get("delimiter", ","),
                "header_lines": settings.get("header_lines", 0),
                "columns": settings.get("columns", []),
                "datetime_code": settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
            }
        else:
            # Fallback settings if no JSON settings available
            file_ext = os.path.splitext(file_info.file_name)[1].lower()
            if file_ext == '.dat':
                parsing_settings = {
                    "delimiter": r"\s+",  # Whitespace delimiter for .dat files
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
                }
            else:
                parsing_settings = {
                    "delimiter": ",",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df['datetime'])"
                }
        
        print(f"[DEBUG] Using parsing settings: {parsing_settings}")
        
        df = parse_winch_dat(full_file_path, parsing_settings)
        
        if df is None or df.empty:
            return [{'label': 'Error: Could not parse winch data file', 'value': 'error'}], None
        
        print(f"[DEBUG] Loaded winch data with {len(df)} rows and columns: {list(df.columns)}")
        
        # Get numeric columns for plotting (excluding datetime-related columns)
        exclude_cols = ['index', 'datetime', 'date', 'time', 'year', 'month', 'day', 'hour', 'minute', 'second']
        numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                       if col.lower() not in exclude_cols]
        
        if not numeric_cols:
            return [{'label': 'No numeric parameters found in winch data', 'value': 'none'}], None
        
        # Create options with icons based on parameter names
        options = []
        for col in sorted(numeric_cols):
            col_lower = col.lower()
            if any(term in col_lower for term in ['depth', 'position', 'altitude', 'wire_out', 'payout']):
                icon = "🌊"
            elif any(term in col_lower for term in ['speed', 'velocity', 'rate']):
                icon = "⚡"
            elif any(term in col_lower for term in ['tension', 'load', 'force', 'weight']):
                icon = "💪"
            elif any(term in col_lower for term in ['pressure']):
                icon = "📊"
            elif any(term in col_lower for term in ['temperature', 'temp']):
                icon = "🌡️"
            elif any(term in col_lower for term in ['winch', 'mode', 'alarm']):
                icon = "🔧"
            else:
                icon = "📈"
            
            options.append({'label': f"{icon} {col}", 'value': col})
        
        # Default to wire_out/payout-related parameter if available, otherwise tension, otherwise first parameter
        wire_params = [col for col in numeric_cols if any(term in col.lower() for term in ['wire_out', 'payout', 'depth'])]
        tension_params = [col for col in numeric_cols if 'tension' in col.lower()]
        
        if wire_params:
            default_value = wire_params[0]
        elif tension_params:
            default_value = tension_params[0]
        else:
            default_value = numeric_cols[0] if numeric_cols else None
        
        print(f"[DEBUG] Winch parameters available: {numeric_cols}")
        print(f"[DEBUG] Default winch parameter: {default_value}")
        return options, default_value
        
    except Exception as e:
        print(f"[DEBUG] Error loading winch parameters: {e}")
        import traceback
        traceback.print_exc()
        return [{'label': f'Error: {str(e)}', 'value': 'error'}], None

# MAIN PLOTTING CALLBACK WITH COMPANION TRACES
@callback(
    [Output('combined-plot', 'figure'), 
     Output('data-info', 'children'), Output('detail-mode-btn', 'children'), 
     Output('mode-indicator', 'children')],
    [Input('sensor-files-dropdown', 'value'), 
     Input('companion-files-dropdown', 'value'),
     Input('winch-files-dropdown', 'value'),
     Input('winch-parameter-dropdown', 'value'),
     Input('winch-enabled-checkbox', 'value'),
     Input('time-range-slider', 'value'),
     Input('parameter-dropdown', 'value'),
     Input('detail-mode-btn', 'n_clicks')],
    [State('combined-plot', 'relayoutData')]
)
def update_combined_plot(selected_sensor_files, companion_sensor_files, winch_file_id, 
                        winch_parameter, winch_enabled, time_range, selected_parameter, 
                        detail_clicks, relayout_data):
    
    # Add callback context protection
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    # Check if detail mode is enabled
    is_detail_mode = (detail_clicks % 2) == 1
    
    # Detect zoom from relayout data
    zoom_start, zoom_end = None, None
    zoom_duration = None
    
    if relayout_data and 'xaxis.range[0]' in relayout_data:
        try:
            zoom_start = pd.to_datetime(relayout_data['xaxis.range[0]'])
            zoom_end = pd.to_datetime(relayout_data['xaxis.range[1]'])
            zoom_duration = (zoom_end - zoom_start).total_seconds()
            print(f"[DEBUG] Plot zoom: {zoom_start} to {zoom_end} ({zoom_duration:.1f}s)")
        except Exception as e:
            print(f"[DEBUG] Error parsing zoom: {e}")
    
    # Set point limits based on detail mode
    if is_detail_mode:
        max_points = None
        mode_desc = "🔍 DETAIL MODE"
        button_text = "📊 Back to Overview Mode"
        mode_indicator = f"Detail Mode: Showing ALL points"
        if zoom_duration:
            mode_indicator += f" ({zoom_duration:.0f}s window)"
    else:
        max_points = 5000
        mode_desc = "📊 OVERVIEW MODE" 
        button_text = "🔍 Show All Points in Current View"
        mode_indicator = "Overview Mode: Click button after zooming to see all points"
    
    # Create subplot figure with shared x-axis
    from plotly.subplots import make_subplots
    
    # Determine if we should show winch plot
    show_winch = winch_enabled and 'enabled' in winch_enabled and winch_file_id and winch_file_id not in ['none', 'error']
    
    if show_winch:
        # Two subplots with shared x-axis
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,  # This is the key - shared x-axis!
            vertical_spacing=0.02,  # Minimal spacing between plots
            subplot_titles=None,  # No titles
            row_heights=[0.6, 0.4]  # Sensor plot bigger than winch plot
        )
    else:
        # Single plot
        fig = make_subplots(rows=1, cols=1)
    
    # Add sensor data traces to the top subplot (row=1)
    sensor_traces_added = add_sensor_traces(fig, selected_sensor_files, companion_sensor_files, 
                                           selected_parameter, time_range, is_detail_mode, 
                                           max_points, zoom_start, zoom_end, row=1)
    
    # Add winch data traces to the bottom subplot (row=2) if enabled
    winch_traces_added = False
    if show_winch:
        winch_traces_added = add_winch_traces(fig, winch_file_id, winch_parameter, 
                                            time_range, is_detail_mode, max_points, 
                                            zoom_start, zoom_end, row=2)
    
    # Configure the layout
    configure_combined_layout(fig, selected_parameter, winch_parameter, show_winch, 
                            zoom_start, zoom_end, mode_desc, zoom_duration)
    
    # Create data info
    data_info = create_combined_data_info(mode_desc, max_points, selected_parameter, 
                                        zoom_duration, is_detail_mode, show_winch)
    
    return fig, data_info, button_text, mode_indicator

def add_sensor_traces(fig, selected_sensor_files, companion_sensor_files, selected_parameter, 
                     time_range, is_detail_mode, max_points, zoom_start, zoom_end, row):
    """Add sensor traces to the subplot"""
    
    # Combine all file lists
    all_files = []
    if selected_sensor_files:
        all_files.extend([(f, 'primary') for f in selected_sensor_files])
    if companion_sensor_files:
        all_files.extend([(f, 'companion') for f in companion_sensor_files])
    
    if not all_files or not selected_parameter or selected_parameter == 'none':
        fig.add_annotation(
            text="Select sensor files and parameter to display data",
            xref="paper", yref="paper", x=0.5, y=0.8,
            showarrow=False, font=dict(size=14, color="gray"),
            row=row, col=1
        )
        return False
    
    # Time filtering from slider
    if time_range and len(time_range) == 2:
        slider_start = pd.to_datetime(time_range[0], unit='s')
        slider_end = pd.to_datetime(time_range[1], unit='s')
        filter_start, filter_end = slider_start, slider_end
    else:
        filter_start, filter_end = None, None
    
    primary_colors = ['blue', 'red', 'darkgreen', 'orange']
    companion_colors = ['lightblue', 'pink', 'lightgreen', 'yellow']
    is_depth_parameter = selected_parameter and 'depth' in selected_parameter.lower()
    
    primary_count = 0
    companion_count = 0
    traces_added = False
    
    for file_id, file_type in all_files:
        df, info = load_sensor_data(file_id)
        if df is None:
            continue
        
        # Apply filters
        if filter_start and filter_end:
            df = df[(df['datetime'] >= filter_start) & (df['datetime'] <= filter_end)]
        
        if zoom_start and zoom_end:
            df = df[(df['datetime'] >= zoom_start) & (df['datetime'] <= zoom_end)]
        
        if df.empty:
            continue
        
        # Apply downsampling
        if not is_detail_mode and max_points and len(df) > max_points:
            step = max(1, len(df) // max_points)
            indices = range(0, len(df), step)[:max_points]
            df = df.iloc[list(indices)]
        
        # Find columns to plot
        numeric_cols = [col for col in df.select_dtypes(include=['number']).columns 
                       if col.lower() not in ['id', 'index']]
        
        if selected_parameter == 'all':
            cols_to_plot = numeric_cols
        else:
            cols_to_plot = [col for col in numeric_cols if col == selected_parameter]
            if not cols_to_plot:
                cols_to_plot = [col for col in numeric_cols if selected_parameter.lower() in col.lower()]
        
        # Add traces
        if file_type == 'primary':
            color = primary_colors[primary_count % len(primary_colors)]
            name_prefix = ""
            primary_count += 1
        else:
            color = companion_colors[companion_count % len(companion_colors)]
            name_prefix = "🔗 "
            companion_count += 1
        
        for col in cols_to_plot:
            if not df[col].isna().all():
                fig.add_trace(
                    go.Scatter(
                        x=df['datetime'], y=df[col],
                        name=f"{name_prefix}{info.file_name}: {col}",
                        mode='lines', 
                        line=dict(color=color, width=2), 
                        opacity=0.8,
                        yaxis=f"y{'' if row == 1 else row}"  # Use correct y-axis
                    ),
                    row=row, col=1
                )
                traces_added = True
    
    return traces_added

def add_winch_traces(fig, winch_file_id, winch_parameter, time_range, is_detail_mode, 
                    max_points, zoom_start, zoom_end, row):
    """Add winch traces to the subplot"""
    
    if not winch_file_id or winch_file_id in ['none', 'error'] or not winch_parameter:
        fig.add_annotation(
            text="Select winch file and parameter",
            xref="paper", yref="paper", x=0.5, y=0.2,
            showarrow=False, font=dict(size=14, color="orange"),
            row=row, col=1
        )
        return False
    
    try:
        # Load winch data
        from utils import parse_winch_dat
        import json
        import os
        
        # Get file info from winch_data table
        with get_connection() as conn:
            query = text("SELECT file_name, file_path, settings FROM winch_data WHERE winch_file_id = :winch_file_id")
            file_info = conn.execute(query, {"winch_file_id": winch_file_id}).fetchone()
        
        if not file_info:
            fig.add_annotation(
                text="Winch file not found",
                xref="paper", yref="paper", x=0.5, y=0.2,
                showarrow=False, font=dict(size=14, color="red"),
                row=row, col=1
            )
            return False
        
        # Parse the JSON settings
        try:
            settings = json.loads(file_info.settings) if file_info.settings else {}
        except json.JSONDecodeError:
            settings = {}
        
        # Construct full file path
        full_file_path = os.path.join(file_info.file_path, file_info.file_name)
        
        # Use the settings from the database
        if settings:
            parsing_settings = {
                "delimiter": settings.get("delimiter", ","),
                "header_lines": settings.get("header_lines", 0),
                "columns": settings.get("columns", []),
                "datetime_code": settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
            }
        else:
            # Fallback settings
            file_ext = os.path.splitext(file_info.file_name)[1].lower()
            if file_ext == '.dat':
                parsing_settings = {
                    "delimiter": r"\s+",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
                }
            else:
                parsing_settings = {
                    "delimiter": ",",
                    "header_lines": 0,
                    "datetime_code": "pd.to_datetime(df['datetime'])"
                }
        
        df = parse_winch_dat(full_file_path, parsing_settings)
        
        if df is None or df.empty:
            fig.add_annotation(
                text="Could not parse winch data",
                xref="paper", yref="paper", x=0.5, y=0.2,
                showarrow=False, font=dict(size=14, color="red"),
                row=row, col=1
            )
            return False
        
        # Apply time filtering
        if time_range and len(time_range) == 2:
            slider_start = pd.to_datetime(time_range[0], unit='s')
            slider_end = pd.to_datetime(time_range[1], unit='s')
            df = df[(df['datetime'] >= slider_start) & (df['datetime'] <= slider_end)]
        
        if zoom_start and zoom_end:
            df = df[(df['datetime'] >= zoom_start) & (df['datetime'] <= zoom_end)]
        
        if df.empty:
            fig.add_annotation(
                text="No winch data in selected time range",
                xref="paper", yref="paper", x=0.5, y=0.2,
                showarrow=False, font=dict(size=14, color="orange"),
                row=row, col=1
            )
            return False
        
        # Apply downsampling
        if not is_detail_mode and max_points and len(df) > max_points:
            step = max(1, len(df) // max_points)
            indices = range(0, len(df), step)[:max_points]
            df = df.iloc[list(indices)]
        
        # Add winch trace
        if winch_parameter in df.columns and not df[winch_parameter].isna().all():
            fig.add_trace(
                go.Scatter(
                    x=df['datetime'], y=df[winch_parameter],
                    name=f"🔧 Winch: {winch_parameter}",
                    mode='lines', 
                    line=dict(color='purple', width=2), 
                    opacity=0.8,
                    yaxis="y2"  # Use second y-axis
                ),
                row=row, col=1
            )
            print(f"[DEBUG] Added winch trace with {len(df)} points")
            return True
        
        return False
        
    except Exception as e:
        print(f"[DEBUG] Error adding winch traces: {e}")
        fig.add_annotation(
            text=f"Error loading winch data: {str(e)[:50]}...",
            xref="paper", yref="paper", x=0.5, y=0.2,
            showarrow=False, font=dict(size=12, color="red"),
            row=row, col=1
        )
        return False

def configure_combined_layout(fig, selected_parameter, winch_parameter, show_winch, 
                            zoom_start, zoom_end, mode_desc, zoom_duration):
    """Configure the layout for the combined subplot figure"""
    
    # Configure layout based on whether winch plot is shown
    if show_winch:
        # Two subplots
        fig.update_layout(
            height=600,
            template="plotly_white",
            hovermode='x unified',  # This creates the shared vertical cursor!
            showlegend=True,
            margin=dict(t=20, b=40, l=60, r=60),
            
            # Configure x-axis (shared between both subplots)
            xaxis=dict(
                title="",  # No title on shared x-axis between plots
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="black",
                spikethickness=2,
                spikemode="across",
                showticklabels=False  # Hide labels on upper x-axis
            ),
            
            # Configure bottom x-axis (only one that shows labels)
            xaxis2=dict(
                title="Time",
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="black", 
                spikethickness=2,
                spikemode="across",
                showticklabels=True
            ),
            
            # Configure sensor y-axis (top plot)
            yaxis=dict(
                title=f"Sensor: {selected_parameter}",
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="red",
                spikethickness=1,
                spikemode="across"
            ),
            
            # Configure winch y-axis (bottom plot)
            yaxis2=dict(
                title=f"Winch: {winch_parameter}",
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="purple",
                spikethickness=1,
                spikemode="across"
            )
        )
        
        # Invert y-axis if depth parameter
        if selected_parameter and 'depth' in selected_parameter.lower():
            fig.update_yaxes(autorange="reversed", row=1, col=1)
        
    else:
        # Single subplot
        fig.update_layout(
            height=600,
            template="plotly_white",
            hovermode='x unified',
            showlegend=True,
            margin=dict(t=20, b=40, l=60, r=60),
            
            xaxis=dict(
                title="Time",
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="black",
                spikethickness=2,
                spikemode="across"
            ),
            
            yaxis=dict(
                title=f"Sensor: {selected_parameter}",
                showgrid=True,
                gridcolor="lightgray",
                showspikes=True,
                spikecolor="red", 
                spikethickness=1,
                spikemode="across"
            )
        )
        
        # Invert y-axis if depth parameter
        if selected_parameter and 'depth' in selected_parameter.lower():
            fig.update_yaxes(autorange="reversed")
    
    # Apply zoom if present
    if zoom_start and zoom_end:
        x_range = [zoom_start, zoom_end]
        if show_winch:
            fig.update_xaxes(range=x_range, row=1, col=1)
            fig.update_xaxes(range=x_range, row=2, col=1)
        else:
            fig.update_xaxes(range=x_range)
        print(f"[DEBUG] Applied zoom range: {x_range}")

def create_combined_data_info(mode_desc, max_points, selected_parameter, zoom_duration, is_detail_mode, show_winch):
    """Create data information display"""
    
    zoom_info = f" (viewing {zoom_duration:.0f}s window)" if zoom_duration else ""
    
    mode_status = html.Div([
        html.Strong(f"{mode_desc}{zoom_info}: "),
        html.Span(f"{'No point limit' if is_detail_mode else f'Max {max_points:,} points per file'}. "),
        html.Span(f"Parameter: {selected_parameter}. "),
        html.Span("✨ True shared x-axis synchronization!", style={'color': 'green', 'fontWeight': 'bold'})
    ], style={'color': 'blue', 'marginBottom': '10px'})
    
    features = [
        html.Li("🎯 Single black vertical cursor spans both plots automatically"),
        html.Li("📊 True shared x-axis - zoom affects both plots simultaneously"),
        html.Li("🔄 Different y-axes for vastly different measurement scales"),
        html.Li("⚡ Built-in Plotly synchronization - no custom code needed")
    ]
    
    if show_winch:
        features.extend([
            html.Li("🌊 Top plot: Sensor data with red horizontal crosshair"),
            html.Li("🔧 Bottom plot: Winch data with purple horizontal crosshair")
        ])
    
    return html.Div([
        mode_status,
        html.H4("✨ Shared Axis Features:", style={'color': '#2c3e50'}),
        html.Ul(features)
    ])

# MAIN ENTRY POINT
if __name__ == '__main__':
    print("🚀 Starting Sensor Data Plotter...")
    print("📊 Dashboard will be available at: http://127.0.0.1:8050")
    print("🔧 Press Ctrl+C to stop the server")
    
    app.run(
        debug=True,           # Enable debug mode
        host='127.0.0.1',     # Listen on localhost
        port=8050,            # Default Dash port
        dev_tools_hot_reload=True,  # Auto-reload on file changes
        dev_tools_ui=True     # Show debug UI
    )
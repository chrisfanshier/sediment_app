import numpy as np
import pandas as pd
from scipy import signal

def detect_trip_time(df, tension_col='WINCH_Tension', depth_cols=None, std_threshold=0.01, edge_buffer=500):
    """
    Detect trip time by finding:
    1. Sharp tension drop (5000 lbs over 2-5 samples) — MAIN signal
    2. All 3 RBR sensors diverge (stop moving together) — confirmation
    
    Args:
        df: DataFrame with datetime index and depth/tension columns
        tension_col: name of tension column
        depth_cols: list of depth column names, or auto-detect if None
        std_threshold: Absolute standard deviation threshold to detect trip onset (default 0.01)
        edge_buffer: number of samples to exclude from start/end to avoid edge effects (default 500)
    
    Returns:
        trip_time (datetime), confidence (0-1), diagnostics dict
    """
    
    # Parse datetime if needed
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        df = df.set_index('datetime')
    elif df.index.name == 'datetime':
        df.index = pd.to_datetime(df.index)
    else:
        raise ValueError("DataFrame must have 'datetime' column or datetime index (from WINCH)")
    
    t = np.arange(len(df))
    
    # Auto-detect depth columns if not provided
    if depth_cols is None:
        depth_cols = [col for col in df.columns if 'Depth' in col]
        if len(depth_cols) < 2:
            raise ValueError(f"Expected at least 2 depth columns, found {len(depth_cols)}")

    
    # Interpolate depth data
    depths = np.array([df[col].interpolate().fillna(method='ffill').fillna(method='bfill').values for col in depth_cols])
    
    # Forward-fill tension (sparse), then smooth
    tension = df[tension_col].fillna(method='ffill').fillna(method='bfill').values
    tension_smooth = signal.savgol_filter(tension, window_length=11, polyorder=2)
    
    # ========== WINCH TRIP ESTIMATE (PRIMARY) ==========
    # Find steepest negative slope in tension (excluding edges)
    d_tension = np.diff(tension_smooth)
    
    # Mask out edge regions
    d_tension_masked = d_tension.copy()
    d_tension_masked[:edge_buffer] = 0  # Suppress start edge
    d_tension_masked[-edge_buffer:] = 0  # Suppress end edge
    
    winch_trip_idx = np.argmin(d_tension_masked)  # Most negative derivative (excluding edges)
    
    # Check if trip is within valid range
    if winch_trip_idx <= edge_buffer or winch_trip_idx >= len(d_tension) - edge_buffer:
        winch_trip_idx = np.argmin(d_tension)  # Fall back to full search
        confidence = 0.3  # Lower confidence due to edge position
    
    tension_drop_magnitude = abs(d_tension[winch_trip_idx])
    
    # ========== RBR TRIP ESTIMATE (SECONDARY) ==========
    # Smooth all 3 depth sensors
    depths_smooth = np.array([signal.savgol_filter(d, window_length=51, polyorder=4) for d in depths])
    d_depths = np.diff(depths_smooth, axis=1)  # velocities for all 3 sensors
    
    # Smooth the velocities to reduce noise
    d_depths_smooth = np.array([signal.savgol_filter(vel, window_length=31, polyorder=2) for vel in d_depths])
    
    # Compute divergence: standard deviation of velocities across sensors
    velocity_std = np.std(d_depths_smooth, axis=0)
    
    # Mask out edge regions
    velocity_std_masked = velocity_std.copy()
    velocity_std_masked[:edge_buffer] = 0
    velocity_std_masked[-edge_buffer:] = 0
    
    # Find maximum divergence point (excluding edges)
    max_divergence_idx = np.argmax(velocity_std_masked)
    
    # Search backwards from max to find where std first exceeds threshold
    rbr_trip_idx = max_divergence_idx
    
    for i in range(max_divergence_idx - 1, max(edge_buffer, max_divergence_idx - 300), -1):
        if velocity_std[i] <= std_threshold:
            rbr_trip_idx = i + 1
            break
    
    if rbr_trip_idx == max_divergence_idx:
        rbr_trip_idx = max_divergence_idx  # If we didn't find onset, use max
    
    # ========== FINAL ESTIMATE ==========
    # Primary: use winch trip
    trip_idx = winch_trip_idx
    trip_time = df.index[trip_idx]
    
    # Confidence based on tension drop magnitude
    tension_baseline_std = np.std(np.diff(tension_smooth[max(0, winch_trip_idx-100):winch_trip_idx]))
    confidence = min(1.0, tension_drop_magnitude / (3 * tension_baseline_std)) if tension_baseline_std > 0 else 0.5
    
    # Calculate actual time offset between winch and RBR trips (using actual timestamps)
    winch_time = df.index[winch_trip_idx]
    rbr_time = df.index[rbr_trip_idx]
    time_offset_seconds = (rbr_time - winch_time).total_seconds()
    
    diagnostics = {
        'trip_idx': trip_idx,
        'trip_time': str(trip_time),
        'confidence': min(1.0, float(confidence)),
        'winch_trip_estimate': {
            'idx': int(winch_trip_idx),
            'time': str(winch_time),
            'tension_drop_lbs': float(tension_drop_magnitude),
            'source': 'PRIMARY (sharp tension drop)',
        },
        'rbr_trip_estimate': {
            'idx': int(rbr_trip_idx),
            'time': str(rbr_time),
            'source': 'SECONDARY (sensor velocity divergence)',
            'offset_from_winch_seconds': float(time_offset_seconds),
        },
        'depth_columns': depth_cols,
    }
    
    return trip_time, min(1.0, float(confidence)), diagnostics
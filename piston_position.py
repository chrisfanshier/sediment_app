import numpy as np
import pandas as pd

def calculate_piston_position(df, barrel_length, trip_time, scope, offset_constant=4.0,
                              time_col='datetime', weight_stand_col=None, release_col=None):
    """
    Calculate piston position based on weight stand and release device depths.
    
    Args:
        df: DataFrame with datetime index and depth columns
        barrel_length: Length of piston corer barrel (m)
        trip_time: datetime when coring device tripped
        scope: Scope of coring device (m)
        offset_constant: Constant offset (default 4.0 m)
        time_col: name of datetime column
        weight_stand_col: name of weight stand depth column
        release_col: name of release device depth column
    
    Returns:
        DataFrame with 'piston_position' column added and 'switched_to_release' column
    """
    
    df = df.copy()
    
    # Parse datetime if needed
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
    
    # Check required columns
    if weight_stand_col not in df.columns:
        raise ValueError(f"Weight stand column '{weight_stand_col}' not found")
    if release_col not in df.columns:
        raise ValueError(f"Release device column '{release_col}' not found")
    
    # Convert trip_time to datetime if string
    if isinstance(trip_time, str):
        trip_time = pd.to_datetime(trip_time)
    
    # Fill missing values
    weight_stand = df[weight_stand_col].fillna(method='ffill').fillna(method='bfill')
    release_device = df[release_col].fillna(method='ffill').fillna(method='bfill')
    
    # Initialize arrays
    piston_position = np.full(len(df), np.nan)
    switched_to_release_array = np.full(len(df), False, dtype=bool)
    switched_to_release = False
    switch_time = None
    
    # Calculate piston position for each row
    for idx in range(len(df)):
        current_time = df[time_col].iloc[idx] 
        
        # Before trip: use weight stand formula
        if current_time is None or current_time < trip_time:
            piston_position[idx] = weight_stand.iloc[idx] + offset_constant + barrel_length
        
        # After trip: check if we should switch to release-based calculation
        else:
            if not switched_to_release:
                difference = abs(release_device.iloc[idx] - weight_stand.iloc[idx])
                
                # Switch to release-based if difference exceeds scope
                if difference > scope:
                    switched_to_release = True
                    switch_time = current_time
            
            switched_to_release_array[idx] = switched_to_release
            
            if switched_to_release:
                piston_position[idx] = release_device.iloc[idx] + scope + barrel_length + offset_constant
            else:
                piston_position[idx] = weight_stand.iloc[idx] + offset_constant + barrel_length
    
    df['piston_position'] = piston_position
    df['switched_to_release'] = switched_to_release_array
    
    return df, switch_time

def get_piston_summary(df, barrel_length, trip_time, scope, offset_constant=4.0,
                       time_col='datetime', weight_stand_col=None, release_col=None):
    """
    Calculate piston position and return summary statistics.
    
    Returns dict with summary metrics and switch_time
    """
    
    result_df, switch_time = calculate_piston_position(
        df, barrel_length, trip_time, scope, offset_constant,
        time_col, weight_stand_col, release_col
    )
    
    piston_pos = result_df['piston_position'].dropna()
    
    summary = {
        'df': result_df,
        'trip_time': trip_time,
        'switch_time': switch_time,
        'min_depth': float(np.nanmin(piston_pos)) if len(piston_pos) > 0 else None,
        'max_depth': float(np.nanmax(piston_pos)) if len(piston_pos) > 0 else None,
        'mean_depth': float(np.nanmean(piston_pos)) if len(piston_pos) > 0 else None,
        'valid_points': int(np.sum(~np.isnan(piston_pos))),
        'total_points': len(result_df)
    }
    
    return summary
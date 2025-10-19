import os

# Root directory for all data files
ROOT_DIRECTORY = os.getenv("FILE_STORAGE_ROOT", "/home/server/project/marssam/marssam_data_files")

# Subdirectories for specific file types
SUBDIRECTORIES = {
    "MSCL Data": "MSCL_Data",
    "RBR Sensor": "Sensor_Data",
    "Star-Oddi Sensor": "Sensor_Data",
    "Winch Data": "winch_data",
    "CT Data": "CT_Data"
}

# Predefined winch data formats
WINCH_FORMATS = {
    "Custom Format": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": [],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
    },
    "Sikuliaq": {
        "delimiter": "\\s+",
        "header_lines": 0,
        "columns": ["year", "month", "day", "hour", "minute", "second", "Winch", "Winch Mode", "Wire_out", "Calc Tension", "Velocity", "Alarm", "Block Length", "Tension"],
        "datetime_code": "pd.to_datetime(df[['year', 'month', 'day', 'hour', 'minute', 'second']])"
    },
    "Armstrong": {
        "delimiter": ",",
        "header_lines": 0,
        "columns": ["timestamp", "offset_datetime", "tension", "speed", "payout", "kgTension?"],
        "datetime_code": "pd.to_datetime(df['timestamp'].str.extract(r'(\\d{4}/\\d{2}/\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3})')[0])"
    },
    "Atlantis": {
        "delimiter": ",",
        "header_lines": 13,
        "columns": ["Date", "Time", "Winch Number", "Tension", "Tension Alarm", "Payout", "Payout Alarm", "Speed", "Speed Alarm", "Max Payout"],
        "datetime_code": "pd.to_datetime(df['Date'] + ' ' + df['Time'], errors='coerce')"
    }
}

# Function to construct full paths
def get_full_path(relative_path):
    """
    Construct the full path for a given relative path.
    """
    return os.path.join(ROOT_DIRECTORY, relative_path)
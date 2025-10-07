import os

# Root directory for all data files
ROOT_DIRECTORY = os.getenv("FILE_STORAGE_ROOT", "/home/server/project/marssam/marssam_data_files")

# Subdirectories for specific file types
SUBDIRECTORIES = {
    "MSCL Data": "MSCL_Data",
    "RBR Sensor": "Sensor_Data",
    "Star-Oddi Sensor": "Sensor_Data",
    "Winch Data": "winch_data"
}

# Function to construct full paths
def get_full_path(relative_path):
    """
    Construct the full path for a given relative path.
    """
    return os.path.join(ROOT_DIRECTORY, relative_path)
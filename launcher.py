"""
Main launcher for Shipside Database applications
Opens all apps in separate browser tabs
"""
import subprocess
import time
import webbrowser
import sys

# Streamlit ports for each app
APPS = [
    {"name": "Main App", "script": "app.py", "port": 8501},
    {"name": "Coring Data Entry", "script": "coring_data_entry.py", "port": 8502},
    {"name": "File Data Entry", "script": "file_data_entry.py", "port": 8503},
    {"name": "Ship Sync", "script": "ship_sync.py", "port": 8504}
]

def main():
    print("=" * 60)
    print("  Starting Shipside Database Applications")
    print("=" * 60)
    print()
    
    processes = []
    
    # Start each Streamlit app on different ports
    for app in APPS:
        print(f"Starting {app['name']} on port {app['port']}...")
        
        process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", app["script"], 
             "--server.port", str(app["port"]),
             "--server.headless", "true"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        processes.append(process)
        time.sleep(2)
    
    # Wait for apps to initialize
    print("\nWaiting for apps to initialize...")
    time.sleep(3)
    
    # Open browser tabs
    print("\nOpening browser tabs...")
    for app in APPS:
        url = f"http://localhost:{app['port']}"
        print(f"  Opening {app['name']}: {url}")
        webbrowser.open(url)
        time.sleep(1)
    
    print("\n" + "=" * 60)
    print("  All apps running!")
    print("=" * 60)
    print("\nURLs:")
    for app in APPS:
        print(f"  - {app['name']}: http://localhost:{app['port']}")
    print("\nPress Ctrl+C to stop all apps.")
    print("=" * 60)
    
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping all applications...")
        for process in processes:
            process.terminate()
        print("All applications stopped.")

if __name__ == "__main__":
    main()
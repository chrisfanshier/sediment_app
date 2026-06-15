"""
Main launcher for Shipside Database applications
Opens all apps in separate browser tabs, or a single app if a port is specified.

Usage:
    python launcher.py           -> starts all apps
    python launcher.py 8501      -> starts only the app on port 8501
"""
import subprocess
import time
import webbrowser
import sys

# Streamlit ports for each app
APPS = [
    {"name": "Main App",           "script": "app.py",               "port": 8501},
    {"name": "Coring Data Entry",  "script": "coring_data_entry.py", "port": 8502},
    {"name": "File Data Entry",    "script": "file_data_entry.py",   "port": 8503},
    {"name": "Ship Sync",          "script": "ship_sync.py",         "port": 8504},
    {"name": "Winch Plotter",      "script": "winch_plot.py",        "port": 8505},
    {"name": "File Sync",          "script": "file_sync.py",         "port": 8506},
    {"name": "CT Manager",         "script": "CT_manager_van.py",    "port": 8507},
]

def main():
    # If a port argument is passed, run only that app
    if len(sys.argv) > 1:
        target_port = sys.argv[1]
        apps_to_run = [a for a in APPS if str(a["port"]) == target_port]
        if not apps_to_run:
            print(f"Error: No app found for port {target_port}")
            print("Available ports: " + ", ".join(str(a["port"]) for a in APPS))
            sys.exit(1)
    else:
        apps_to_run = APPS  # Default: start everything

    print("=" * 60)
    if len(apps_to_run) == 1:
        print(f"  Starting {apps_to_run[0]['name']}")
    else:
        print("  Starting Shipside Database Applications")
    print("=" * 60)
    print()

    processes = []

    # Start each Streamlit app on its port
    for app in apps_to_run:
        print(f"Starting {app['name']} on port {app['port']}...")

        process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", app["script"],
             "--server.port", str(app["port"]),
             "--server.headless", "true",
             "--server.enableXsrfProtection", "false",
             "--server.enableCORS", "false"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        processes.append(process)
        time.sleep(2)

    # Wait for apps to initialize
    print("\nWaiting for app(s) to initialize...")
    time.sleep(3)

    # Open browser tab(s)
    print("\nOpening browser tab(s)...")
    for app in apps_to_run:
        url = f"http://localhost:{app['port']}"
        print(f"  Opening {app['name']}: {url}")
        webbrowser.open(url)
        time.sleep(1)

    print("\n" + "=" * 60)
    print("  App(s) running!")
    print("=" * 60)
    print("\nURLs:")
    for app in apps_to_run:
        print(f"  - {app['name']}: http://localhost:{app['port']}")
    print("\nPress Ctrl+C to stop.")
    print("=" * 60)

    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping application(s)...")
        for process in processes:
            process.terminate()
        print("Done.")

if __name__ == "__main__":
    main()

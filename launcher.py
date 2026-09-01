"""
Main launcher for Shipside Database applications
Opens all apps in separate browser tabs, or a single app if a port is specified.

Usage:
    python launcher.py           -> starts all Streamlit apps + desktop apps
    python launcher.py 8501      -> starts only the Streamlit app on port 8501
    python launcher.py dredge    -> starts only the Dredge App (PySide6 desktop)
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

# PySide6 desktop apps (no browser / port)
DESKTOP_APPS = [
    {"name": "Dredge App", "key": "dredge", "module": "dredge_app"},
]


def start_desktop_app(app):
    """Launch a PySide6 desktop application as a module."""
    print(f"Starting {app['name']}...")
    return subprocess.Popen([sys.executable, "-m", app["module"]])


def main():
    # Desktop-only launch: python launcher.py dredge
    if len(sys.argv) > 1 and not sys.argv[1].isdigit():
        key = sys.argv[1].lower()
        desktop_apps = [
            d for d in DESKTOP_APPS
            if d["key"] == key or d["module"].lower() == key
        ]
        if not desktop_apps:
            print(f"Error: No app found for '{sys.argv[1]}'")
            print("Available desktop apps: " + ", ".join(d["key"] for d in DESKTOP_APPS))
            print("Available Streamlit ports: " + ", ".join(str(a["port"]) for a in APPS))
            sys.exit(1)

        print("=" * 60)
        print(f"  Starting {desktop_apps[0]['name']}")
        print("=" * 60)
        print()
        process = start_desktop_app(desktop_apps[0])
        try:
            process.wait()
        except KeyboardInterrupt:
            print("\n\nStopping application...")
            process.terminate()
            print("Done.")
        return

    # If a port argument is passed, run only that Streamlit app
    if len(sys.argv) > 1:
        target_port = sys.argv[1]
        apps_to_run = [a for a in APPS if str(a["port"]) == target_port]
        if not apps_to_run:
            print(f"Error: No app found for port {target_port}")
            print("Available ports: " + ", ".join(str(a["port"]) for a in APPS))
            print("Available desktop apps: " + ", ".join(d["key"] for d in DESKTOP_APPS))
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
        )
        processes.append(process)
        time.sleep(2)

    # Start desktop apps when launching the full suite
    if len(sys.argv) <= 1:
        for app in DESKTOP_APPS:
            processes.append(start_desktop_app(app))
            time.sleep(1)

    # Wait for apps to initialize
    print("\nWaiting for app(s) to initialize...")
    time.sleep(3)

    # Open browser tab(s) for Streamlit apps
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
    if len(sys.argv) <= 1:
        for app in DESKTOP_APPS:
            print(f"  - {app['name']}: desktop window")
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

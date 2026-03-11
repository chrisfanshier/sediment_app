# ShipsideDB Remote Setup — macOS

> Mac-adapted version of the Windows setup guide.
> All paths use `~/ShipsideDB` as the root (equivalent to `C:\ShipsideDB` on Windows).

---

## Step 1 — Download PostgreSQL (macOS Binary)

Download the macOS binary version of PostgreSQL 13.xx from:

```
https://get.enterprisedb.com/postgresql/postgresql-13.16-1-osx-binaries.zip
```

> ⚠️ Make sure to select the macOS (osx) binary — not the Windows x64 version.

---

## Step 2 — Extract and Place Files

Extract the zip and place the folder at:

```
~/ShipsideDB/
```

---

## Step 3 — Rename Extracted Folder

Rename the extracted folder so the structure is:

```
~/ShipsideDB/postgresql/
```

---

## Step 4 — Initialize the Database

Open Terminal and run:

```bash
cd ~/ShipsideDB/postgresql/bin

# Initialize database
./initdb -D ../data -U postgres -W -E UTF8

# Connect to postgres
./psql -d postgres
```

Then inside psql, create the superuser role:

```sql
CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD 'madmaxfuryroad';
```

> ℹ️ On macOS, executables do not have `.exe` extensions. Use `./initdb` and `./psql` instead of `.\initdb.exe` etc.

---

## Step 5 — Create Start and Stop Scripts

Instead of `.bat` files, create shell scripts. Save these in `~/ShipsideDB/`:

**startdatabase.sh**
```bash
#!/bin/bash
~/ShipsideDB/postgresql/bin/pg_ctl -D ~/ShipsideDB/postgresql/data start
```

**stopdatabase.sh**
```bash
#!/bin/bash
~/ShipsideDB/postgresql/bin/pg_ctl -D ~/ShipsideDB/postgresql/data stop
```

Make them executable:

```bash
chmod +x ~/ShipsideDB/startdatabase.sh
chmod +x ~/ShipsideDB/stopdatabase.sh
```

---

## Step 6 — Test Database Startup

```bash
~/ShipsideDB/startdatabase.sh
```

---

## Step 7 — Install Git

Check if Git is already installed:

```bash
git --version
```

If not installed, macOS will prompt you to install Xcode Command Line Tools, which includes Git. Follow the on-screen prompt, then verify:

```bash
git --version  # Should show: git version 2.x.x
```

> ℹ️ No manual PATH setup needed — Git is automatically available in Terminal after installation.

---

## Step 8 — Clone the Repository

```bash
cd ~/ShipsideDB/app

# Clone and checkout the shipside branch:
git clone -b shipside https://github.com/chrisfanshier/sediment_app.git .
```

---

## Step 9 — Install Python 3.11

Download the macOS installer from:

```
https://www.python.org/ftp/python/3.11.9/python-3.11.9-macos11.pkg
```

After installation, add Python to your PATH:

```bash
echo 'export PATH="/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Verify:

```bash
python3 --version  # Should show: Python 3.11.x
pip3 --version     # Should show: pip 23.x.x
```

> ℹ️ On macOS, use `python3` and `pip3` instead of `python` and `pip`, unless your PATH alias is configured otherwise.

---

## Step 10 — Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it (macOS syntax — different from Windows!)
source venv/bin/activate

# You should see (venv) in your prompt

# Install all packages with exact versions
pip install -r requirements.txt
```

> ⚠️ The Windows activation command (`.\venv\Scripts\Activate.ps1`) does **not** work on Mac. Always use: `source venv/bin/activate`

---

## Step 11 — Export Database from VM

Run this on the VM (not your Mac):

```bash
pg_dump -U postgres \
  --no-owner \
  --no-acl \
  --clean \
  --if-exists \
  sediment_cores > export<date>.sql
```

---

## Step 12 — Transfer to Mac via SCP

SCP works natively in macOS Terminal:

```bash
scp user@vm-address:/path/to/export<date>.sql ~/ShipsideDB/
```

---

## Step 13 — Create Database and Restore

```bash
cd ~/ShipsideDB/postgresql/bin

# Create database
./psql -U postgres -c "CREATE DATABASE test_shipside;"

# Restore from root folder
./psql -U postgres -d shipside -f ~/ShipsideDB/<export_dbname>.sql
```

---

## Step 14 — Run prepare_db.py

With your virtual environment active, run `prepare_db.py` and select which cruises to load:

```bash
source venv/bin/activate
python prepare_db.py
```

---

## Step 15 — Update Config Root Directory

In the config file, update `ROOT_DIRECTORY` to use the Mac path:

```python
ROOT_DIRECTORY = "/Users/yourname/ShipsideDB"
```

Or for portability across usernames:

```python
import os
ROOT_DIRECTORY = os.path.expanduser("~/ShipsideDB")
```

Then run:

```bash
python copy_files.py
```

---

## Step 16 — Ready to Go

Make sure your `.sh` start/stop scripts are in `~/ShipsideDB/` and are executable (see Step 5). You're ready to run the app.

---

## Key Differences from Windows

| | Windows | macOS |
|---|---|---|
| Shell | PowerShell / cmd | Terminal |
| Scripts | `.bat` files | `.sh` shell scripts |
| Executables | `initdb.exe`, `psql.exe` | `initdb`, `psql` |
| venv activation | `.\venv\Scripts\Activate.ps1` | `source venv/bin/activate` |
| Python command | `python` / `pip` | `python3` / `pip3` |
| Root path | `C:\ShipsideDB` | `~/ShipsideDB` |

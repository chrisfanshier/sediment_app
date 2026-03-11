1.	Download postgres binary version 13.xx from: https://get.enterprisedb.com/postgresql/postgresql-13.16-1-windows-x64-binaries.zip
2.Extract and place in c:\shipside_db
3. Rename to make sure extracted folder is called \postgresql\
4. # Open PowerShell
    cd C:\ShipsideDB\postgresql\bin
# Initialize database
.\initdb.exe -D ..\data -U postgres -W -E UTF8
# Create postgres superuser for consistency with central VM
.\psql.exe -d postgres
CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD 'madmaxfuryroad';

5. Copy start and stop database .bat files
6. Click STARTDATABASE files to make sure it starts ok
7. Install git
# Download Git for Windows:
# https://git-scm.com/download/win
# During installation, use default settings (they're fine)
# Important options:
# ☑ Add Git to PATH
# ☑ Use Git from command line and 3rd party software
# After installation, verify:
git --version
# Should show: git version 2.x.x
8. In command prompt/powershell  
cd C:\ShipsideDB\app

# Clone and checkout the shipside branch:
git clone -b shipside https://github.com/chrisfanshier/sediment_app.git .
9. Install Python
# Download Python 3.11 from:
https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
# During installation:
☑ Add Python to PATH (CRITICAL!)
☑ Install pip

# After installation, verify:
python --version
# Should show: Python 3.11.x

pip --version
# Should show: pip 23.x.x
10. create virtual environment
# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\Activate.ps1

# You should see (venv) in your prompt

# Install all packages with exact versions
pip install -r requirements.txt

11. Create exportable database from vm:
# Best practice dump command
pg_dump -U postgres \
  --no-owner \
  --no-acl \
  --clean \
  --if-exists \
  sediment_cores > export<date>.sql
12. transfer to laptop with scp command to shipside_DB root directory
13. create blank database and restore export database
cd C:\ShipsideDB\postgresql\bin

# Create database
.\psql.exe -U postgres -c "CREATE DATABASE test_shipside;"

# Restore from root folder
.\psql.exe -U postgres -d shipside -f C:\ShipsideDB\<export_dbname>.sql
14. run prepare_db.py in virtual entironment and select which cruises you want to load
15. make sure config root directory is set to: ROOT_DIRECTORY = r"C:\ShipsideDB"
 exists and run copy_files.py
16. have .bat files in root directory and you should be ready to go!





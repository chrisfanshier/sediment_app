import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request, redirect, session, url_for
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Needed for session

# Set up your Postgres connection string
engine = create_engine("postgresql+psycopg2://postgres:madmaxfuryroad@localhost:5432/sediment_cores")

# === Settings UI ===
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        session["CT_ROOT"] = request.form.get("ct_root")
        session["DB_PATH"] = request.form.get("db_path")
        return redirect(url_for("view_ct"))
    # Show form with current values or defaults
    ct_root = session.get("CT_ROOT", "None")
    db_path = session.get("DB_PATH", "original_test.db")
    html = """
    <h2>CT Crawler Settings</h2>
    <form method="post">
        <label>CT Root Folder:</label>
        <input type="text" name="ct_root" value="{{ ct_root }}" size="80"><br><br>
        <label>SQLite DB Path:</label>
        <input type="text" name="db_path" value="{{ db_path }}" size="40"><br><br>
        <button type="submit">Save Settings</button>
    </form>
    """
    return render_template_string(html, ct_root=ct_root, db_path=db_path)

def get_ct_root():
    # Default to None if not set
    return session.get("CT_ROOT")

def get_db_path():
    return session.get("DB_PATH", "original_test.db")

# === Database setup ===
# def init_db():
#     conn = sqlite3.connect(get_db_path())
#     cur = conn.cursor()
#     cur.execute("""
#         CREATE TABLE IF NOT EXISTS ct_xml (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             core_id INTEGER,
#             core_name TEXT,
#             section_id INTEGER,
#             scan_id TEXT,
#             image_type TEXT,
#             processing_stage TEXT,
#             section_number TEXT,
#             xml_path TEXT,
#             tiff_folder TEXT,
#             xml_root_tag TEXT,
#             timestamp TEXT
#         )
#     """)
#     cur.execute("""
#         CREATE TABLE IF NOT EXISTS local_changes (
#             table_name TEXT,
#             record_id INTEGER,
#             change_type TEXT,
#             timestamp TEXT,
#             synced INTEGER DEFAULT 0
#         )
#     """)
#     cur.execute("""
#         CREATE TABLE IF NOT EXISTS ct_xml_staging (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             core_id INTEGER,
#             core_name TEXT,
#             section_id INTEGER,
#             scan_id TEXT,
#             image_type TEXT,
#             processing_stage TEXT,
#             section_number TEXT,
#             xml_path TEXT,
#             tiff_folder TEXT,
#             xml_root_tag TEXT,
#             timestamp TEXT
#         )
#     """)
#     conn.commit()
#     conn.close()

# === XML Parsing ===
def parse_ct_xml(xml_path):
    """Extracts original metadata fields directly from XML and root tag."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        root_tag = root.tag

        def get_text(*tags):
            for tag in tags:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    return el.text.strip()
            return None

        section_id = get_text("Section-ID", "section-id", "sectionID")
        if not section_id:
            section_id = get_text("Section-Number", "section-number")

        core_name = get_text("Core-ID", "coreID")
        # Normalize: uppercase and replace underscores with hyphens
        if core_name:
            core_name = core_name.strip().replace("_", "-").upper()

        total_scanned_length = get_text("Total-Scanned-Length", "total-scanned-length")

        data = {
            "core_name": core_name,
            "scan_id": get_text("Scan-ID", "scanID"),
            "section_id": section_id,
            "image_type": get_text("Image-Type", "image-type"),
            "processing_stage": get_text("Processing-Stage", "processing-stage"),
            "section_number": section_id,
            "xml_root_tag": root_tag,
            "total_scanned_length": total_scanned_length
        }
        return data

    except Exception as e:
        print(f"Error parsing XML {xml_path}: {e}")
        return None

# === Folder scanning ===
def scan_ct_folders():
    found = []
    ct_root = get_ct_root()
    # Find the parent directory of CT_Data
    ct_data_parent = os.path.dirname(ct_root.rstrip(os.sep))
    for root, dirs, files in os.walk(ct_root):
        xmls = [f for f in files if f.lower().endswith(".xml")]
        for xml_file in xmls:
            xml_path = os.path.join(root, xml_file)
            meta = parse_ct_xml(xml_path)
            if meta and meta["core_name"]:
                # Store paths relative to CT_Data parent, so they always start with CT_Data/...
                rel_xml_path = os.path.relpath(xml_path, ct_data_parent)
                rel_tiff_folder = os.path.relpath(root, ct_data_parent)
                record = {
                    **meta,
                    "xml_path": rel_xml_path,
                    "tiff_folder": rel_tiff_folder,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                found.append(record)
    return found

# def save_ct_folders_to_db(records):
#     conn = sqlite3.connect(get_db_path())
#     cur = conn.cursor()
#     cur.execute("SELECT xml_path FROM ct_xml")
#     existing_xmls = {row[0] for row in cur.fetchall()}
#     new_records = []
#     for r in records:
#         if r["xml_path"] not in existing_xmls:
#             core_name = r["core_name"].strip() if r["core_name"] else None
#             cur.execute("SELECT core_id FROM cores WHERE TRIM(core_name) = ?", (core_name,))
#             core_row = cur.fetchone()
#             core_id = core_row[0] if core_row else None

#             section_id = None
#             if core_id and r["section_number"]:
#                 cur.execute("SELECT section_id FROM sections WHERE core_id = ? AND section_number = ?", (core_id, r["section_number"]))
#                 section_row = cur.fetchone()
#                 section_id = section_row[0] if section_row else None

#             cur.execute("""
#                 INSERT INTO ct_xml (
#                     core_id, core_name, section_id, scan_id, image_type,
#                     processing_stage, section_number,
#                     xml_path, tiff_folder, xml_root_tag, timestamp
#                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#             """, (
#                 core_id, r["core_name"], section_id, r["scan_id"], r["image_type"],
#                 r["processing_stage"], r["section_number"],
#                 r["xml_path"], r["tiff_folder"], r["xml_root_tag"], r["timestamp"]
#             ))
#             record_id = cur.lastrowid
#             log_local_change(conn, "ct_xml", record_id, "insert")
#             new_records.append(r)
#     conn.commit()
#     conn.close()
#     return new_records

def save_ct_folders_to_staging(records):
    with engine.begin() as conn:
        existing_xmls = set(
            row[0] for row in conn.execute(text("SELECT xml_path FROM ct_xml_staging"))
        )
        new_records = []
        manual_review = []  # Collect records needing manual interpretation
        for r in records:
            reason = None
            if r["xml_path"] in existing_xmls:
                reason = "Already in staging"
            elif not r["core_name"]:
                reason = "Missing core_name"
            # Add more checks as needed

            core_name = r["core_name"].strip() if r["core_name"] else None
            core_row = conn.execute(
                text("SELECT core_id FROM cores WHERE TRIM(core_name) = :core_name"),
                {"core_name": core_name}
            ).fetchone()
            core_id = core_row[0] if core_row else None

            section_id = None
            section_number = r["section_number"]
            try:
                section_number_int = int(section_number)
            except (TypeError, ValueError):
                section_number_int = None

            # Only create a new section if section_number is an integer and no section exists
            if core_id and section_number_int is not None:
                section_row = conn.execute(
                    text("SELECT section_id FROM sections WHERE core_id = :core_id AND section_number = :section_number"),
                    {"core_id": core_id, "section_number": section_number_int}
                ).fetchone()
                if not section_row:
                    try:
                        section_length = float(r.get("total_scanned_length")) if r.get("total_scanned_length") else None
                    except Exception:
                        section_length = None
                    remarks = "section created by ct data"
                    result = conn.execute(
                        text("""
                            INSERT INTO sections (core_id, section_number, section_length, remarks)
                            VALUES (:core_id, :section_number, :section_length, :remarks)
                            RETURNING section_id
                        """),
                        {
                            "core_id": core_id,
                            "section_number": section_number_int,
                            "section_length": section_length,
                            "remarks": remarks
                        }
                    )
                    section_id = result.scalar()
                else:
                    section_id = section_row[0]
            elif core_id and section_number_int is None:
                # Section number not integer, flag for manual review
                manual_review.append(r)
                reason = "Non-integer section number, needs manual interpretation"

            if reason:
                print(f"SKIPPED: {r['xml_path']} | Reason: {reason}")
                continue

            conn.execute(
                text("""
                    INSERT INTO ct_xml_staging (
                        core_id, core_name, section_id, scan_id, image_type,
                        processing_stage, section_number,
                        xml_path, tiff_folder, xml_root_tag, timestamp
                    ) VALUES (
                        :core_id, :core_name, :section_id, :scan_id, :image_type,
                        :processing_stage, :section_number,
                        :xml_path, :tiff_folder, :xml_root_tag, :timestamp
                    )
                """),
                dict(
                    core_id=core_id, core_name=r["core_name"], section_id=section_id,
                    scan_id=r["scan_id"], image_type=r["image_type"],
                    processing_stage=r["processing_stage"], section_number=section_number,
                    xml_path=r["xml_path"], tiff_folder=r["tiff_folder"],
                    xml_root_tag=r["xml_root_tag"], timestamp=r["timestamp"]
                )
            )
            new_records.append(r)
        # Optionally, log or return manual_review for further handling
        return new_records

# === Flask routes ===
@app.route("/crawl_ct", methods=["GET"])
def crawl_ct():
    records = scan_ct_folders()
    new_records = save_ct_folders_to_staging(records)
    return jsonify({
        "new_records": new_records,
        "skipped": len(records) - len(new_records),
        "total_found": len(records)
    })

@app.route("/view_ct", methods=["GET"])
def view_ct():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM ct_xml_staging ORDER BY timestamp DESC"))
        rows = [dict(row._mapping) for row in result.fetchall()]

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CT Scan Records (Staging)</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 2em; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; }
            th { background-color: #f2f2f2; cursor: pointer; }
            tr:nth-child(even) { background-color: #f9f9f9; }
        </style>
        <script>
            function sortTable(n) {
              var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
              table = document.getElementById("ctTable");
              switching = true;
              dir = "asc";
              while (switching) {
                switching = false;
                rows = table.rows;
                for (i = 1; i < (rows.length - 1); i++) {
                  shouldSwitch = false;
                  x = rows[i].getElementsByTagName("TD")[n];
                  y = rows[i + 1].getElementsByTagName("TD")[n];
                  if (dir == "asc") {
                    if (x.innerHTML.toLowerCase() > y.innerHTML.toLowerCase()) {
                      shouldSwitch = true;
                      break;
                    }
                  } else if (dir == "desc") {
                    if (x.innerHTML.toLowerCase() < y.innerHTML.toLowerCase()) {
                      shouldSwitch = true;
                      break;
                    }
                  }
                }
                if (shouldSwitch) {
                  rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                  switching = true;
                  switchcount++;
                } else {
                  if (switchcount == 0 && dir == "asc") {
                    dir = "desc";
                    switching = true;
                  }
                }
              }
            }
        </script>
    </head>
    <body>
        <h2>CT Scan Records (Staging)</h2>
        {% if rows %}
        <table id="ctTable">
            <tr>
                {% for col in rows[0].keys() %}
                <th onclick="sortTable({{ loop.index0 }})">{{ col }}</th>
                {% endfor %}
            </tr>
            {% for row in rows %}
            <tr>
                {% for col in row.keys() %}
                <td>{{ row[col] }}</td>
                {% endfor %}
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p>No CT records found.</p>
        {% endif %}
    </body>
    </html>
    """
    return render_template_string(html, rows=rows)

@app.route("/unmapped_sections", methods=["GET", "POST"])
def unmapped_sections():
    show_only_unmapped = request.args.get("only_unmapped", "off") == "on"
    show_filepaths = request.args.get("show_filepaths", "on") == "on"
    with engine.connect() as conn:
        # --- Get all cruises with cores ---
        cruises = conn.execute(text("""
            SELECT DISTINCT cruises.cruise_id, cruises.cruise_name
            FROM cores
            JOIN cruises ON cores.cruise_id = cruises.cruise_id
            ORDER BY cruises.cruise_name
        """)).fetchall()
        selected_cruise_id = request.args.get("cruise_id")
        if not selected_cruise_id and cruises:
            selected_cruise_id = str(cruises[0].cruise_id)

        # --- Get all cores for the selected cruise ---
        cores = conn.execute(
            text("SELECT core_id, core_name FROM cores WHERE cruise_id = :cruise_id ORDER BY core_name"),
            {"cruise_id": selected_cruise_id}
        ).fetchall()
        core_dict = {core.core_id: core.core_name for core in cores}

        # --- Get all sections for all cores in the cruise ---
        sections_by_core = {}
        for core in cores:
            sections = conn.execute(
                text("SELECT section_id, section_number FROM sections WHERE core_id = :core_id ORDER BY section_number"),
                {"core_id": core.core_id}
            ).fetchall()
            sections_by_core[core.core_id] = [dict(sec._mapping) for sec in sections]

        # --- Get all XML-derived rows ---
        query = """
            SELECT core_id, core_name, section_number, section_id, COUNT(*) as n_xmls
            FROM ct_xml_staging
            GROUP BY core_id, core_name, section_number, section_id
        """
        result = conn.execute(text(query))
        all_sections = [dict(row._mapping) for row in result.fetchall()]
        # Optionally filter by cruise (show only rows with core_id in this cruise or unmapped)
        filtered_sections = [
            row for row in all_sections
            if (row["core_id"] in core_dict or row["core_id"] is None)
        ]
        if show_only_unmapped:
            filtered_sections = [row for row in filtered_sections if row["section_id"] is None]

        # --- Get filepaths for each (core_name, section_number) pair ---
        filepaths_by_core_section = {}
        for row in filtered_sections:
            paths = conn.execute(
                text("""
                    SELECT DISTINCT xml_path
                    FROM ct_xml_staging
                    WHERE core_name = :core_name AND section_number = :section_number
                """),
                {"core_name": row["core_name"], "section_number": row["section_number"]}
            ).fetchall()
            filepaths_by_core_section[(row["core_name"], row["section_number"])] = [p[0] for p in paths]

    html = """
    <h2>Assign CT XML Section Associations</h2>
    <form method="get" action="/unmapped_sections">
        <label for="cruise_id">Cruise:</label>
        <select name="cruise_id" id="cruise_id" onchange="this.form.submit()">
            {% for cruise in cruises %}
            <option value="{{ cruise.cruise_id }}" {% if cruise.cruise_id|string == selected_cruise_id %}selected{% endif %}>{{ cruise.cruise_name }}</option>
            {% endfor %}
        </select>
        <label>
            <input type="checkbox" name="only_unmapped" value="on" {% if show_only_unmapped %}checked{% endif %} onchange="this.form.submit()">
            Show only unmapped sections
        </label>
        <label>
            <input type="checkbox" name="show_filepaths" value="on" {% if show_filepaths %}checked{% endif %} onchange="this.form.submit()">
            Show filepaths
        </label>
        <button type="submit">Apply Filter</button>
    </form>
    <form method="post" action="/map_section">
    <input type="hidden" name="cruise_id" value="{{ selected_cruise_id }}">
    <table>
        <tr>
            <th>Core Name (XML)</th>
            <th>Section Number (XML)</th>
            <th>Records</th>
            <th>Assign Core</th>
            <th>Assign Section</th>
            {% if show_filepaths %}
            <th>Filepaths</th>
            {% endif %}
        </tr>
        {% for row in filtered_sections %}
        <tr>
            <td>{{ row['core_name'] }}</td>
            <td>{{ row['section_number'] }}</td>
            <td>{{ row['n_xmls'] }}</td>
            <td>
                <select name="core_id_{{ loop.index0 }}">
                    <option value="">-- Select Core --</option>
                    {% for core in cores %}
                    <option value="{{ core.core_id }}" {% if core.core_id == row['core_id'] %}selected{% endif %}>{{ core.core_name }}</option>
                    {% endfor %}
                </select>
            </td>
            <td>
                <select name="section_id_{{ loop.index0 }}">
                    <option value="">-- Select Section --</option>
                    {% for sec in sections_by_core.get(row['core_id'], []) %}
                    <option value="{{ sec['section_id'] }}" {% if sec['section_id'] == row['section_id'] %}selected{% endif %}>{{ sec['section_number'] }}</option>
                    {% endfor %}
                </select>
            </td>
            {% if show_filepaths %}
            <td>
                <ul style="max-width:350px;overflow-x:auto;">
                {% for path in filepaths_by_core_section[(row['core_name'], row['section_number'])] %}
                    <li style="font-size:smaller;">{{ path }}</li>
                {% endfor %}
                </ul>
            </td>
            {% endif %}
            <input type="hidden" name="row_index_{{ loop.index0 }}" value="{{ row['core_name'] }}|||{{ row['section_number'] }}">
        </tr>
        {% endfor %}
    </table>
    <button type="submit">Update Mappings</button>
    </form>
    """
    return render_template_string(
        html,
        filtered_sections=filtered_sections,
        cores=cores,
        cruises=cruises,
        selected_cruise_id=selected_cruise_id,
        sections_by_core=sections_by_core,
        show_only_unmapped=show_only_unmapped,
        filepaths_by_core_section=filepaths_by_core_section,
        show_filepaths=show_filepaths
    )

@app.route("/map_section", methods=["POST"])
def map_section():
    cruise_id = request.form.get("cruise_id")
    with engine.begin() as conn:
        # Loop over all rows by index
        i = 0
        while True:
            row_key = f"row_index_{i}"
            if row_key not in request.form:
                break
            core_id = request.form.get(f"core_id_{i}")
            section_id = request.form.get(f"section_id_{i}")
            core_name, section_number = request.form[row_key].split("|||")
            # Only update if a core or section is selected
            if core_id:
                conn.execute(
                    text("""
                        UPDATE ct_xml_staging
                        SET core_id = :core_id
                        WHERE core_name = :core_name AND section_number = :section_number
                    """),
                    {"core_id": core_id, "core_name": core_name, "section_number": section_number}
                )
            if section_id:
                conn.execute(
                    text("""
                        UPDATE ct_xml_staging
                        SET section_id = :section_id
                        WHERE core_name = :core_name AND section_number = :section_number
                    """),
                    {"section_id": section_id, "core_name": core_name, "section_number": section_number}
                )
            i += 1
    return redirect(url_for("unmapped_sections", cruise_id=cruise_id))

@app.route("/", methods=["GET", "POST"])
def select_cruise_folder():
    base_dir = "/home/server/project/marssam/marssam_data_files/CT_Data"
    cruise_folders = sorted([
        name for name in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, name))
    ])
    if request.method == "POST":
        selected = request.form.get("cruise_folder")
        if selected:
            session["CT_ROOT"] = os.path.join(base_dir, selected)
            return redirect(url_for("view_ct"))
    html = """
    <h2>Select Cruise Folder</h2>
    <form method="post">
        <label for="cruise_folder">Cruise Folder:</label>
        <select name="cruise_folder" id="cruise_folder">
            {% for folder in cruise_folders %}
            <option value="{{ folder }}">{{ folder }}</option>
            {% endfor %}
        </select>
        <button type="submit">Select</button>
    </form>
    """
    return render_template_string(html, cruise_folders=cruise_folders)

def approve_and_import_staging():
    with engine.begin() as conn:
        # Insert all staging records into main table
        conn.execute(text("""
            INSERT INTO ct_xml (
                core_id, core_name, section_id, scan_id, image_type,
                processing_stage, section_number, xml_path, tiff_folder, xml_root_tag, timestamp
            )
            SELECT
                core_id, core_name, section_id, scan_id, image_type,
                processing_stage, section_number, xml_path, tiff_folder, xml_root_tag, timestamp
            FROM ct_xml_staging
        """))
        # Purge staging table
        conn.execute(text("DELETE FROM ct_xml_staging"))

@app.route("/dashboard")
def dashboard():
    html = """
    <h2>CT Crawler Dashboard</h2>
    <ul>
        <li><a href="{{ url_for('select_cruise_folder') }}">Select Cruise Folder</a></li>
        <li><a href="{{ url_for('crawl_ct_page') }}">Crawl CT Files (add to staging)</a></li>
        <li><a href="{{ url_for('view_ct') }}">View Staging Records</a></li>
        <li><a href="{{ url_for('unmapped_cores') }}">Review/Assign Core Associations</a></li>
        <li><a href="{{ url_for('unmapped_sections') }}">Review/Assign Section Associations</a></li>
        <li>
            <form action="{{ url_for('approve_import') }}" method="post" style="display:inline;">
                <button type="submit" onclick="return confirm('Approve and import all staged records?')">Approve & Import to Main Table</button>
            </form>
        </li>
    </ul>
    """
    return render_template_string(html)

# Add a POST route for approve/import
@app.route("/approve_import", methods=["POST"])
def approve_import():
    approve_and_import_staging()
    return redirect(url_for('dashboard'))

@app.route("/")
def home():
    return redirect(url_for("dashboard"))

@app.route("/clear_staging", methods=["POST"])
def clear_staging():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ct_xml_staging"))
    return redirect(url_for('dashboard'))

@app.route("/crawl_ct_page", methods=["GET", "POST"])
def crawl_ct_page():
    base_dir = "/home/server/project/marssam/marssam_data_files/CT_Data"
    cruise_folders = sorted([
        name for name in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, name))
    ])
    selected = session.get("CT_ROOT", os.path.join(base_dir, cruise_folders[0]) if cruise_folders else "")
    message = ""
    if request.method == "POST":
        selected = request.form.get("cruise_folder")
        if selected:
            session["CT_ROOT"] = os.path.join(base_dir, selected)
            # Optionally, trigger the crawl here or redirect to /crawl_ct
            return redirect(url_for("crawl_ct"))
    html = """
    <h2>Crawl CT Files</h2>
    <form method="post" style="display: flex; align-items: center; gap: 1em;">
        <label for="cruise_folder">Cruise Folder:</label>
        <select name="cruise_folder" id="cruise_folder">
            {% for folder in cruise_folders %}
            <option value="{{ folder }}" {% if session_CT_ROOT and session_CT_ROOT.endswith(folder) %}selected{% endif %}>{{ folder }}</option>
            {% endfor %}
        </select>
        <button type="submit">Set & Crawl</button>
    </form>
    <p>{{ message }}</p>
    """
    return render_template_string(html, cruise_folders=cruise_folders, session_CT_ROOT=selected, message=message)

@app.route("/unmapped_cores", methods=["GET", "POST"])
def unmapped_cores():
    with engine.connect() as conn:
        # Get all cruises with cores
        cruises = conn.execute(text("""
            SELECT DISTINCT cruises.cruise_id, cruises.cruise_name
            FROM cores
            JOIN cruises ON cores.cruise_id = cruises.cruise_id
            ORDER BY cruises.cruise_name
        """)).fetchall()

        # Handle cruise selection
        selected_cruise_id = request.args.get("cruise_id")
        if not selected_cruise_id and cruises:
            selected_cruise_id = str(cruises[0].cruise_id)

        # Find core_names in staging with no matching core_id
        result = conn.execute(text("""
            SELECT DISTINCT core_name
            FROM ct_xml_staging
            WHERE core_id IS NULL OR core_id NOT IN (SELECT core_id FROM cores)
        """))
        unmapped_core_names = [row[0] for row in result.fetchall()]

        # Get only cores for the selected cruise
        cores = conn.execute(
            text("SELECT core_id, core_name FROM cores WHERE cruise_id = :cruise_id"),
            {"cruise_id": selected_cruise_id}
        ).fetchall()

    if request.method == "POST":
        selected_core_id = request.form.get("core_id")
        selected_core_name = request.form.get("unmapped_core_name")
        cruise_id = request.form.get("cruise_id")
        if selected_core_id and selected_core_name:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE ct_xml_staging SET core_id = :core_id WHERE core_name = :core_name"),
                    {"core_id": selected_core_id, "core_name": selected_core_name}
                )
        return redirect(url_for("unmapped_cores", cruise_id=cruise_id))

    html = """
    <h2>Unmapped Core Names</h2>
    <form method="get">
        <label for="cruise_id">Cruise:</label>
        <select name="cruise_id" id="cruise_id" onchange="this.form.submit()">
            {% for cruise in cruises %}
            <option value="{{ cruise.cruise_id }}" {% if cruise.cruise_id|string == selected_cruise_id %}selected{% endif %}>{{ cruise.cruise_name }}</option>
            {% endfor %}
        </select>
    </form>
    <form method="post">
        <input type="hidden" name="cruise_id" value="{{ selected_cruise_id }}">
        <table>
            <tr><th>Unmapped Core Name</th><th>Assign to Existing Core</th><th>Action</th></tr>
            {% for unmapped in unmapped_core_names %}
            <tr>
                <td>
                    <input type="hidden" name="unmapped_core_name" value="{{ unmapped }}">
                    {{ unmapped }}
                </td>
                <td>
                    <select name="core_id">
                        {% for core in cores %}
                        <option value="{{ core.core_id }}">{{ core.core_name }}</option>
                        {% endfor %}
                    </select>
                </td>
                <td>
                    <button type="submit">Assign</button>
                </td>
            </tr>
            {% endfor %}
        </table>
    </form>
    """
    return render_template_string(
        html,
        unmapped_core_names=unmapped_core_names,
        cores=cores,
        cruises=cruises,
        selected_cruise_id=selected_cruise_id
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5905, debug=True)
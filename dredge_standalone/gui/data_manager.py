"""Data Manager page — metadata entry and file registration.

Standalone replacement for the Streamlit entry apps: create cruises and
dredge deployments, and register sensor / winch / USBL files.  Registered
files are copied into the project folder; winch and USBL files are pooled
per cruise (matched to dredges by time overlap at load time) while sensor
files are assigned to a specific dredge.
"""
from pyqtgraph.Qt import QtWidgets, QtCore

from .. import APP_NAME
from ..formats import SENSOR_MEASUREMENTS
from ..persistence import file_parsers as fp
from .winch_dialog import WinchImportDialog


def _dt_edit(initial=None) -> QtWidgets.QDateTimeEdit:
    """A UTC date-time editor with sensible display format."""
    edit = QtWidgets.QDateTimeEdit()
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    edit.setCalendarPopup(True)
    edit.setTimeSpec(QtCore.Qt.UTC)
    if initial:
        edit.setDateTime(QtCore.QDateTime.fromString(str(initial)[:19], "yyyy-MM-dd HH:mm:ss"))
    else:
        now = QtCore.QDateTime.currentDateTimeUtc()
        edit.setDateTime(now)
    return edit


def _dt_value(edit: QtWidgets.QDateTimeEdit) -> str:
    return edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")


class CruiseDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, cruise=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Cruise" if cruise else "New Cruise")
        form = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit(cruise["cruise_name"] if cruise else "")
        self.vessel_edit = QtWidgets.QLineEdit((cruise and cruise["vessel_name"]) or "")
        self.notes_edit = QtWidgets.QLineEdit((cruise and cruise["notes"]) or "")

        form.addRow("Cruise name*:", self.name_edit)
        form.addRow("Vessel:", self.vessel_edit)
        form.addRow("Notes:", self.notes_edit)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a cruise name.")
            return
        self.accept()

    def values(self):
        return (
            self.name_edit.text().strip(),
            self.vessel_edit.text().strip() or None,
            self.notes_edit.text().strip() or None,
        )


class DredgeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, dredge=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Dredge" if dredge else "New Dredge")
        form = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit(dredge["dredge_name"] if dredge else "")
        self.start_edit = _dt_edit(dredge and dredge["start_datetime"])
        self.end_edit = _dt_edit(dredge and dredge["end_datetime"])
        self.usbl_dist_edit = QtWidgets.QLineEdit(
            "" if not dredge or dredge["usbl_distance_m"] is None else str(dredge["usbl_distance_m"])
        )
        self.usbl_dist_edit.setPlaceholderText("Optional, meters")
        self.notes_edit = QtWidgets.QLineEdit((dredge and dredge["notes"]) or "")

        form.addRow("Dredge name*:", self.name_edit)
        form.addRow("Start (UTC)*:", self.start_edit)
        form.addRow("End (UTC)*:", self.end_edit)
        form.addRow("USBL distance (m):", self.usbl_dist_edit)
        form.addRow("Notes:", self.notes_edit)

        hint = QtWidgets.QLabel(
            "Start/end define the deployment window: sensor, winch and USBL\n"
            "data are truncated to this range in the viewer."
        )
        hint.setStyleSheet("color: gray; font-size: 10px;")
        form.addRow(hint)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a dredge name.")
            return
        if self.end_edit.dateTime() <= self.start_edit.dateTime():
            QtWidgets.QMessageBox.warning(
                self, "Invalid Window", "End time must be after start time."
            )
            return
        if self.usbl_dist_edit.text().strip():
            try:
                float(self.usbl_dist_edit.text().strip())
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid Value", "USBL distance must be a number (meters)."
                )
                return
        self.accept()

    def values(self):
        usbl_dist = self.usbl_dist_edit.text().strip()
        return (
            self.name_edit.text().strip(),
            _dt_value(self.start_edit),
            _dt_value(self.end_edit),
            float(usbl_dist) if usbl_dist else None,
            self.notes_edit.text().strip() or None,
        )


class SensorFileDialog(QtWidgets.QDialog):
    """Metadata for one or more Star-Oddi sensor files being registered."""

    def __init__(self, file_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Register Sensor File(s)")
        form = QtWidgets.QFormLayout(self)

        files_label = QtWidgets.QLabel("\n".join(file_names))
        files_label.setStyleSheet("font-weight: bold;")
        form.addRow("File(s):", files_label)

        self.location_edit = QtWidgets.QLineEdit()
        self.location_edit.setPlaceholderText("e.g., Weight Stand, Release Device, Trigger Core/Weight")
        form.addRow("Sensor location*:", self.location_edit)

        measurements_box = QtWidgets.QWidget()
        m_layout = QtWidgets.QHBoxLayout(measurements_box)
        m_layout.setContentsMargins(0, 0, 0, 0)
        self.measure_checks = {}
        for m in SENSOR_MEASUREMENTS:
            cb = QtWidgets.QCheckBox(m)
            self.measure_checks[m] = cb
            m_layout.addWidget(cb)
        form.addRow("Measurements*:", measurements_box)

        self.remarks_edit = QtWidgets.QLineEdit()
        self.remarks_edit.setPlaceholderText("Optional remarks")
        form.addRow("Remarks:", self.remarks_edit)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self.location_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Field", "Please enter a sensor location.")
            return
        if not any(cb.isChecked() for cb in self.measure_checks.values()):
            QtWidgets.QMessageBox.warning(self, "Missing Field", "Please select at least one measurement.")
            return
        self.accept()

    def values(self):
        measurements = [m for m, cb in self.measure_checks.items() if cb.isChecked()]
        return (
            self.location_edit.text().strip(),
            ", ".join(measurements),
            self.remarks_edit.text().strip() or None,
        )


class UsblImportDialog(QtWidgets.QDialog):
    """Preview auto-detected start/end times for USBL files before saving."""

    def __init__(self, file_paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Register USBL File(s)")
        self.resize(700, 420)
        self.rows = []  # (path, start, end)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Detected start/end times (from $PSONLLD records, with midnight-rollover handling):"
        ))

        table = QtWidgets.QTableWidget(len(file_paths), 3)
        table.setHorizontalHeaderLabels(["File", "Start (UTC)", "End (UTC)"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        import os
        self._has_failures = False
        for i, path in enumerate(file_paths):
            start, end = fp.parse_usbl_first_last(path)
            if start is None or end is None:
                # Fallback: full parse, take min/max
                df = fp.load_usbl_file(path)
                if df is not None and not df.empty:
                    dt = df["datetime"].dt.tz_localize(None)
                    start, end = dt.min(), dt.max()

            self.rows.append((path, start, end))
            table.setItem(i, 0, QtWidgets.QTableWidgetItem(os.path.basename(path)))
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(start) if start is not None else "⚠ not detected"))
            table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(end) if end is not None else "⚠ not detected"))
            if start is None or end is None:
                self._has_failures = True
        table.resizeColumnsToContents()
        layout.addWidget(table)

        if self._has_failures:
            warn = QtWidgets.QLabel(
                "⚠ Some files have no detectable times. They can still be saved, but they will\n"
                "never match a dredge window (time-overlap matching needs start/end). Check that\n"
                "the filename contains the date as YYYYMMDD and the file has $PSONLLD records."
            )
            warn.setStyleSheet("color: #b36b00;")
            layout.addWidget(warn)

        form = QtWidgets.QFormLayout()
        self.device_edit = QtWidgets.QLineEdit()
        self.device_edit.setPlaceholderText("e.g., dredge, multicore")
        self.transponder_edit = QtWidgets.QLineEdit()
        self.transponder_edit.setPlaceholderText("e.g., Ranger2")
        self.remarks_edit = QtWidgets.QLineEdit()
        form.addRow("Sampling device:", self.device_edit)
        form.addRow("Transponder type:", self.transponder_edit)
        form.addRow("Remarks:", self.remarks_edit)
        layout.addLayout(form)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def values(self):
        return (
            self.rows,
            self.device_edit.text().strip() or None,
            self.transponder_edit.text().strip() or None,
            self.remarks_edit.text().strip() or None,
        )


class DataManagerPage(QtWidgets.QWidget):
    """Cruise/dredge metadata entry + file registration."""

    dataChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self._cruises = []
        self._dredges = []
        self._build_ui()
        self._update_enabled()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # ── cruise row ────────────────────────────────────────────────
        cruise_group = QtWidgets.QGroupBox("Cruise")
        cruise_layout = QtWidgets.QHBoxLayout(cruise_group)

        cruise_layout.addWidget(QtWidgets.QLabel("Cruise:"))
        self.cruise_combo = QtWidgets.QComboBox()
        self.cruise_combo.setMinimumWidth(250)
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_selected)
        cruise_layout.addWidget(self.cruise_combo)

        self.new_cruise_btn = QtWidgets.QPushButton("New Cruise…")
        self.new_cruise_btn.clicked.connect(self._new_cruise)
        cruise_layout.addWidget(self.new_cruise_btn)

        self.edit_cruise_btn = QtWidgets.QPushButton("Edit…")
        self.edit_cruise_btn.clicked.connect(self._edit_cruise)
        cruise_layout.addWidget(self.edit_cruise_btn)

        self.delete_cruise_btn = QtWidgets.QPushButton("Delete")
        self.delete_cruise_btn.clicked.connect(self._delete_cruise)
        cruise_layout.addWidget(self.delete_cruise_btn)

        cruise_layout.addStretch()
        cruise_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        layout.addWidget(cruise_group)

        # ── splitter: dredges | files ─────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # dredges
        dredge_group = QtWidgets.QGroupBox("Dredge deployments")
        dredge_layout = QtWidgets.QVBoxLayout(dredge_group)

        self.dredge_table = QtWidgets.QTableWidget(0, 4)
        self.dredge_table.setHorizontalHeaderLabels(
            ["Name", "Start (UTC)", "End (UTC)", "USBL dist (m)"]
        )
        self.dredge_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.dredge_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.dredge_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.dredge_table.horizontalHeader().setStretchLastSection(True)
        self.dredge_table.itemSelectionChanged.connect(self._update_enabled)
        dredge_layout.addWidget(self.dredge_table)

        dredge_btns = QtWidgets.QHBoxLayout()
        self.add_dredge_btn = QtWidgets.QPushButton("Add Dredge…")
        self.add_dredge_btn.clicked.connect(self._add_dredge)
        dredge_btns.addWidget(self.add_dredge_btn)
        self.edit_dredge_btn = QtWidgets.QPushButton("Edit…")
        self.edit_dredge_btn.clicked.connect(self._edit_dredge)
        dredge_btns.addWidget(self.edit_dredge_btn)
        self.delete_dredge_btn = QtWidgets.QPushButton("Delete")
        self.delete_dredge_btn.clicked.connect(self._delete_dredge)
        dredge_btns.addWidget(self.delete_dredge_btn)
        dredge_btns.addStretch()
        dredge_layout.addLayout(dredge_btns)

        splitter.addWidget(dredge_group)

        # files
        files_group = QtWidgets.QGroupBox("Data files")
        files_layout = QtWidgets.QVBoxLayout(files_group)

        self.files_tabs = QtWidgets.QTabWidget()

        # sensor tab
        sensor_tab = QtWidgets.QWidget()
        sensor_layout = QtWidgets.QVBoxLayout(sensor_tab)
        sensor_hint = QtWidgets.QLabel(
            "Star-Oddi .dat / .acc files, assigned to the dredge selected on the left."
        )
        sensor_hint.setStyleSheet("color: gray; font-size: 10px;")
        sensor_layout.addWidget(sensor_hint)
        self.sensor_table = QtWidgets.QTableWidget(0, 5)
        self.sensor_table.setHorizontalHeaderLabels(
            ["Dredge", "File", "Location", "Measurements", "Remarks"]
        )
        self._setup_file_table(self.sensor_table)
        sensor_layout.addWidget(self.sensor_table)
        sensor_btns = QtWidgets.QHBoxLayout()
        self.add_sensor_btn = QtWidgets.QPushButton("Add Sensor File(s)…")
        self.add_sensor_btn.clicked.connect(self._add_sensor_files)
        sensor_btns.addWidget(self.add_sensor_btn)
        self.remove_sensor_btn = QtWidgets.QPushButton("Remove")
        self.remove_sensor_btn.clicked.connect(self._remove_sensor_file)
        sensor_btns.addWidget(self.remove_sensor_btn)
        sensor_btns.addStretch()
        sensor_layout.addLayout(sensor_btns)
        self.files_tabs.addTab(sensor_tab, "Sensor (Star-Oddi)")

        # winch tab
        winch_tab = QtWidgets.QWidget()
        winch_layout = QtWidgets.QVBoxLayout(winch_tab)
        winch_hint = QtWidgets.QLabel(
            "Pooled per cruise; matched to dredges by time overlap when the viewer loads them."
        )
        winch_hint.setStyleSheet("color: gray; font-size: 10px;")
        winch_layout.addWidget(winch_hint)
        self.winch_table = QtWidgets.QTableWidget(0, 4)
        self.winch_table.setHorizontalHeaderLabels(["File", "Start (UTC)", "End (UTC)", "Notes"])
        self._setup_file_table(self.winch_table)
        winch_layout.addWidget(self.winch_table)
        winch_btns = QtWidgets.QHBoxLayout()
        self.add_winch_btn = QtWidgets.QPushButton("Add Winch File…")
        self.add_winch_btn.clicked.connect(self._add_winch_file)
        winch_btns.addWidget(self.add_winch_btn)
        self.remove_winch_btn = QtWidgets.QPushButton("Remove")
        self.remove_winch_btn.clicked.connect(self._remove_winch_file)
        winch_btns.addWidget(self.remove_winch_btn)
        winch_btns.addStretch()
        winch_layout.addLayout(winch_btns)
        self.files_tabs.addTab(winch_tab, "Winch")

        # usbl tab
        usbl_tab = QtWidgets.QWidget()
        usbl_layout = QtWidgets.QVBoxLayout(usbl_tab)
        usbl_hint = QtWidgets.QLabel(
            "Pooled per cruise; matched to dredges by time overlap when the viewer loads them."
        )
        usbl_hint.setStyleSheet("color: gray; font-size: 10px;")
        usbl_layout.addWidget(usbl_hint)
        self.usbl_table = QtWidgets.QTableWidget(0, 5)
        self.usbl_table.setHorizontalHeaderLabels(
            ["File", "Start (UTC)", "End (UTC)", "Device", "Transponder"]
        )
        self._setup_file_table(self.usbl_table)
        usbl_layout.addWidget(self.usbl_table)
        usbl_btns = QtWidgets.QHBoxLayout()
        self.add_usbl_btn = QtWidgets.QPushButton("Add USBL File(s)…")
        self.add_usbl_btn.clicked.connect(self._add_usbl_files)
        usbl_btns.addWidget(self.add_usbl_btn)
        self.remove_usbl_btn = QtWidgets.QPushButton("Remove")
        self.remove_usbl_btn.clicked.connect(self._remove_usbl_file)
        usbl_btns.addWidget(self.remove_usbl_btn)
        usbl_btns.addStretch()
        usbl_layout.addLayout(usbl_btns)
        self.files_tabs.addTab(usbl_tab, "USBL")

        files_layout.addWidget(self.files_tabs)
        splitter.addWidget(files_group)
        splitter.setSizes([450, 750])

        layout.addWidget(splitter, stretch=1)

    @staticmethod
    def _setup_file_table(table: QtWidgets.QTableWidget):
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)

    # ── store handling ────────────────────────────────────────────────

    def set_store(self, store):
        self.store = store
        self.refresh()

    def _update_enabled(self):
        has_store = self.store is not None
        has_cruise = has_store and self._current_cruise() is not None
        has_dredge = has_cruise and self._current_dredge() is not None

        self.new_cruise_btn.setEnabled(has_store)
        self.edit_cruise_btn.setEnabled(has_cruise)
        self.delete_cruise_btn.setEnabled(has_cruise)
        self.add_dredge_btn.setEnabled(has_cruise)
        self.edit_dredge_btn.setEnabled(has_dredge)
        self.delete_dredge_btn.setEnabled(has_dredge)
        self.add_sensor_btn.setEnabled(has_dredge)
        self.remove_sensor_btn.setEnabled(has_cruise)
        self.add_winch_btn.setEnabled(has_cruise)
        self.remove_winch_btn.setEnabled(has_cruise)
        self.add_usbl_btn.setEnabled(has_cruise)
        self.remove_usbl_btn.setEnabled(has_cruise)

    def _current_cruise(self):
        idx = self.cruise_combo.currentIndex()
        if 0 <= idx < len(self._cruises):
            return self._cruises[idx]
        return None

    def _current_dredge(self):
        row = self.dredge_table.currentRow()
        if 0 <= row < len(self._dredges):
            return self._dredges[row]
        return None

    def refresh(self, keep_selection=True):
        """Reload everything from the store."""
        prev_cruise_id = None
        if keep_selection:
            cruise = self._current_cruise()
            prev_cruise_id = cruise["cruise_id"] if cruise else None

        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        self._cruises = self.store.fetch_cruises() if self.store else []
        for cr in self._cruises:
            label = cr["cruise_name"]
            if cr["vessel_name"]:
                label += f" — {cr['vessel_name']}"
            self.cruise_combo.addItem(label)
        restored = 0
        if prev_cruise_id is not None:
            for i, cr in enumerate(self._cruises):
                if cr["cruise_id"] == prev_cruise_id:
                    restored = i
                    break
        self.cruise_combo.setCurrentIndex(restored if self._cruises else -1)
        self.cruise_combo.blockSignals(False)

        self._refresh_cruise_details()

    def _on_cruise_selected(self, index):
        self._refresh_cruise_details()

    def _refresh_cruise_details(self):
        cruise = self._current_cruise()

        # dredges
        self.dredge_table.setRowCount(0)
        self._dredges = []
        if cruise is not None:
            self._dredges = self.store.fetch_dredges(cruise["cruise_id"])
            self.dredge_table.setRowCount(len(self._dredges))
            for i, d in enumerate(self._dredges):
                usbl_dist = "" if d["usbl_distance_m"] is None else str(d["usbl_distance_m"])
                for j, value in enumerate([d["dredge_name"], d["start_datetime"],
                                           d["end_datetime"], usbl_dist]):
                    self.dredge_table.setItem(i, j, QtWidgets.QTableWidgetItem(value or ""))
            self.dredge_table.resizeColumnsToContents()

        # files
        self._refresh_file_tables()
        self._update_enabled()

    def _refresh_file_tables(self):
        cruise = self._current_cruise()

        self.sensor_table.setRowCount(0)
        self.winch_table.setRowCount(0)
        self.usbl_table.setRowCount(0)
        self._sensor_rows = []
        self._winch_rows = []
        self._usbl_rows = []

        if cruise is None:
            return

        self._sensor_rows = self.store.fetch_sensor_files_for_cruise(cruise["cruise_id"])
        self.sensor_table.setRowCount(len(self._sensor_rows))
        for i, r in enumerate(self._sensor_rows):
            for j, value in enumerate([r["dredge_name"], r["file_name"],
                                       r["sensor_location"], r["sensor_type"], r["remarks"]]):
                self.sensor_table.setItem(i, j, QtWidgets.QTableWidgetItem(value or ""))
        self.sensor_table.resizeColumnsToContents()

        self._winch_rows = self.store.fetch_winch_files(cruise["cruise_id"])
        self.winch_table.setRowCount(len(self._winch_rows))
        for i, r in enumerate(self._winch_rows):
            for j, value in enumerate([r["file_name"], r["start_time"], r["end_time"], r["notes"]]):
                self.winch_table.setItem(i, j, QtWidgets.QTableWidgetItem(value or ""))
        self.winch_table.resizeColumnsToContents()

        self._usbl_rows = self.store.fetch_usbl_files(cruise["cruise_id"])
        self.usbl_table.setRowCount(len(self._usbl_rows))
        for i, r in enumerate(self._usbl_rows):
            for j, value in enumerate([r["file_name"], r["start_time"], r["end_time"],
                                       r["sampling_device"], r["transponder_type"]]):
                self.usbl_table.setItem(i, j, QtWidgets.QTableWidgetItem(value or ""))
        self.usbl_table.resizeColumnsToContents()

    def _notify_changed(self):
        self._refresh_cruise_details()
        self.dataChanged.emit()

    # ── cruise actions ────────────────────────────────────────────────

    def _new_cruise(self):
        dialog = CruiseDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            name, vessel, notes = dialog.values()
            try:
                self.store.add_cruise(name, vessel, notes)
            except Exception as exc:  # noqa: BLE001 (e.g. UNIQUE violation)
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not add cruise:\n{exc}")
                return
            self.refresh(keep_selection=False)
            # select the new cruise
            for i, cr in enumerate(self._cruises):
                if cr["cruise_name"] == name:
                    self.cruise_combo.setCurrentIndex(i)
                    break
            self.dataChanged.emit()

    def _edit_cruise(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        dialog = CruiseDialog(self, cruise=cruise)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            name, vessel, notes = dialog.values()
            try:
                self.store.update_cruise(cruise["cruise_id"], name, vessel, notes)
            except Exception as exc:  # noqa: BLE001
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not update cruise:\n{exc}")
                return
            self.refresh()
            self.dataChanged.emit()

    def _delete_cruise(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Cruise",
            f"Delete cruise '{cruise['cruise_name']}'?\n\n"
            "This removes all its dredges, registered files (including the copies\n"
            "in the project folder) and annotations. This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.store.delete_cruise(cruise["cruise_id"])
            self.refresh(keep_selection=False)
            self.dataChanged.emit()

    # ── dredge actions ────────────────────────────────────────────────

    def _add_dredge(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        dialog = DredgeDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            name, start, end, usbl_dist, notes = dialog.values()
            try:
                self.store.add_dredge(cruise["cruise_id"], name, start, end, usbl_dist, notes)
            except Exception as exc:  # noqa: BLE001
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not add dredge:\n{exc}")
                return
            self._notify_changed()

    def _edit_dredge(self):
        dredge = self._current_dredge()
        if dredge is None:
            return
        dialog = DredgeDialog(self, dredge=dredge)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            name, start, end, usbl_dist, notes = dialog.values()
            try:
                self.store.update_dredge(dredge["dredge_id"], name, start, end, usbl_dist, notes)
            except Exception as exc:  # noqa: BLE001
                QtWidgets.QMessageBox.critical(self, "Error", f"Could not update dredge:\n{exc}")
                return
            self._notify_changed()

    def _delete_dredge(self):
        dredge = self._current_dredge()
        if dredge is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Dredge",
            f"Delete dredge '{dredge['dredge_name']}'?\n\n"
            "This removes its sensor files and annotations. This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.store.delete_dredge(dredge["dredge_id"])
            self._notify_changed()

    # ── sensor file actions ───────────────────────────────────────────

    def _add_sensor_files(self):
        dredge = self._current_dredge()
        if dredge is None:
            QtWidgets.QMessageBox.information(
                self, "Select Dredge",
                "Select the dredge deployment these sensor files belong to first."
            )
            return

        import os
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select Star-Oddi Sensor File(s)", "",
            "Star-Oddi files (*.dat *.acc);;All files (*)"
        )
        if not paths:
            return

        dialog = SensorFileDialog([os.path.basename(p) for p in paths], self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        location, measurements, remarks = dialog.values()

        errors = []
        for path in paths:
            try:
                self.store.add_sensor_file(dredge["dredge_id"], path, location, measurements, remarks)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{os.path.basename(path)}: {exc}")
        if errors:
            QtWidgets.QMessageBox.warning(self, "Some Files Failed", "\n".join(errors))
        self._notify_changed()

    def _remove_sensor_file(self):
        row = self.sensor_table.currentRow()
        if not (0 <= row < len(self._sensor_rows)):
            return
        record = self._sensor_rows[row]
        if self._confirm_remove(record["file_name"]):
            self.store.delete_sensor_file(record["sensor_file_id"])
            self._notify_changed()

    # ── winch file actions ────────────────────────────────────────────

    def _add_winch_file(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Winch File", "", "All files (*)"
        )
        if not path:
            return

        dialog = WinchImportDialog(path, self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return

        try:
            self.store.add_winch_file(
                cruise["cruise_id"], path, dialog.settings,
                start_time=dialog.start_time, end_time=dialog.end_time,
                notes=dialog.notes or None,
            )
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not save winch file:\n{exc}")
            return
        self._notify_changed()

    def _remove_winch_file(self):
        row = self.winch_table.currentRow()
        if not (0 <= row < len(self._winch_rows)):
            return
        record = self._winch_rows[row]
        if self._confirm_remove(record["file_name"]):
            self.store.delete_winch_file(record["winch_file_id"])
            self._notify_changed()

    # ── usbl file actions ─────────────────────────────────────────────

    def _add_usbl_files(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select USBL File(s)", "",
            "USBL files (*.txt *.csv *.usbl);;All files (*)"
        )
        if not paths:
            return

        dialog = UsblImportDialog(paths, self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        rows, device, transponder, remarks = dialog.values()

        import os
        errors = []
        for path, start, end in rows:
            try:
                self.store.add_usbl_file(
                    cruise["cruise_id"], path, start_time=start, end_time=end,
                    sampling_device=device, transponder_type=transponder, remarks=remarks,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{os.path.basename(path)}: {exc}")
        if errors:
            QtWidgets.QMessageBox.warning(self, "Some Files Failed", "\n".join(errors))
        self._notify_changed()

    def _remove_usbl_file(self):
        row = self.usbl_table.currentRow()
        if not (0 <= row < len(self._usbl_rows)):
            return
        record = self._usbl_rows[row]
        if self._confirm_remove(record["file_name"]):
            self.store.delete_usbl_file(record["usbl_file_id"])
            self._notify_changed()

    # ── helpers ───────────────────────────────────────────────────────

    def _confirm_remove(self, file_name) -> bool:
        return QtWidgets.QMessageBox.question(
            self, "Remove File",
            f"Remove '{file_name}' from the project?\n\n"
            "The copy inside the project folder will be deleted.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        ) == QtWidgets.QMessageBox.Yes

"""Data Manager — cruises, cores, sensor files, and winch files."""
from __future__ import annotations

from pyqtgraph.Qt import QtWidgets, QtCore

from ..formats import SENSOR_LOCATIONS
from ..persistence.project import ProjectStore
from .winch_dialog import WinchImportDialog


def _dt_edit(initial=None) -> QtWidgets.QDateTimeEdit:
    edit = QtWidgets.QDateTimeEdit()
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    edit.setCalendarPopup(True)
    edit.setTimeSpec(QtCore.Qt.UTC)
    if initial:
        edit.setDateTime(QtCore.QDateTime.fromString(str(initial)[:19], "yyyy-MM-dd HH:mm:ss"))
    else:
        edit.setDateTime(QtCore.QDateTime.currentDateTimeUtc())
    return edit


def _dt_value(edit: QtWidgets.QDateTimeEdit) -> str:
    return edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")


def _optional_float(text: str):
    text = (text or "").strip()
    if not text:
        return None
    return float(text)


class CruiseDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, cruise=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Cruise" if cruise else "New Cruise")
        form = QtWidgets.QFormLayout(self)
        self.name_edit = QtWidgets.QLineEdit(cruise["cruise_name"] if cruise else "")
        self.vessel_edit = QtWidgets.QLineEdit((cruise and cruise.get("vessel_name")) or "")
        self.notes_edit = QtWidgets.QLineEdit((cruise and cruise.get("notes")) or "")
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


class CoreDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, core=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Core" if core else "New Core")
        form = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit(core["core_name"] if core else "")
        self.type_edit = QtWidgets.QLineEdit((core and core.get("core_type")) or "Jumbo Piston Core")
        self.length_edit = QtWidgets.QLineEdit("" if not core or core.get("core_length") is None else str(core["core_length"]))
        self.scope_edit = QtWidgets.QLineEdit("" if not core or core.get("scope") is None else str(core["scope"]))
        self.start_edit = _dt_edit(core and core.get("start_datetime"))
        self.end_edit = _dt_edit(core and core.get("end_datetime"))
        self.trigger_line_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_line_length") is None else str(core["trigger_line_length"])
        )
        self.trigger_core_len_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_length") is None else str(core["trigger_core_length"])
        )
        self.trigger_pen_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_penetration") is None else str(core["trigger_core_penetration"])
        )
        self.trigger_recovery_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_recovery") is None else str(core["trigger_core_recovery"])
        )
        self.piston_recovery_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("piston_core_recovery") is None else str(core["piston_core_recovery"])
        )
        self.pig_edit = QtWidgets.QLineEdit((core and core.get("pig_weights")) or "")
        self.wire_edit = QtWidgets.QLineEdit((core and core.get("wire_type")) or "")
        self.notes_edit = QtWidgets.QLineEdit((core and core.get("notes")) or "")

        form.addRow("Core name*:", self.name_edit)
        form.addRow("Core type:", self.type_edit)
        form.addRow("Core length (ft):", self.length_edit)
        form.addRow("Scope (ft):", self.scope_edit)
        form.addRow("Deploy start (UTC):", self.start_edit)
        form.addRow("Deploy end (UTC):", self.end_edit)
        form.addRow("Trigger line length (ft):", self.trigger_line_edit)
        form.addRow("Trigger core length (ft):", self.trigger_core_len_edit)
        form.addRow("Trigger core penetration (m):", self.trigger_pen_edit)
        form.addRow("Trigger core recovery:", self.trigger_recovery_edit)
        form.addRow("Piston core recovery:", self.piston_recovery_edit)
        form.addRow("Pig weights:", self.pig_edit)
        form.addRow("Wire type:", self.wire_edit)
        form.addRow("Notes:", self.notes_edit)

        hint = QtWidgets.QLabel(
            "Deployment start/end are used to match winch files.\n"
            "Missing fields won't block analysis — modes degrade gracefully."
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
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a core name.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "core_name": self.name_edit.text().strip(),
            "core_type": self.type_edit.text().strip() or None,
            "core_length": _optional_float(self.length_edit.text()),
            "scope": _optional_float(self.scope_edit.text()),
            "start_datetime": _dt_value(self.start_edit),
            "end_datetime": _dt_value(self.end_edit),
            "trigger_line_length": _optional_float(self.trigger_line_edit.text()),
            "trigger_core_length": _optional_float(self.trigger_core_len_edit.text()),
            "trigger_core_penetration": _optional_float(self.trigger_pen_edit.text()),
            "trigger_core_recovery": _optional_float(self.trigger_recovery_edit.text()),
            "piston_core_recovery": _optional_float(self.piston_recovery_edit.text()),
            "pig_weights": self.pig_edit.text().strip() or None,
            "wire_type": self.wire_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }


class DataManagerPage(QtWidgets.QWidget):
    dataChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store: ProjectStore | None = None
        self._cruise_id: int | None = None
        self._core_id: int | None = None
        self._build_ui()

    def set_store(self, store: ProjectStore | None):
        self.store = store
        self._set_enabled(store is not None)
        self._refresh_cruises()
        self._cruise_id = None
        self._core_id = None
        self._refresh_cores()
        self._refresh_sensor_files()
        self._refresh_winch_files()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        cruise_row = QtWidgets.QHBoxLayout()
        cruise_row.addWidget(QtWidgets.QLabel("Cruise:"))
        self.cruise_combo = QtWidgets.QComboBox()
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        cruise_row.addWidget(self.cruise_combo, stretch=1)
        self.add_cruise_btn = QtWidgets.QPushButton("New Cruise")
        self.add_cruise_btn.clicked.connect(self._add_cruise)
        self.edit_cruise_btn = QtWidgets.QPushButton("Edit")
        self.edit_cruise_btn.clicked.connect(self._edit_cruise)
        self.del_cruise_btn = QtWidgets.QPushButton("Delete")
        self.del_cruise_btn.clicked.connect(self._delete_cruise)
        cruise_row.addWidget(self.add_cruise_btn)
        cruise_row.addWidget(self.edit_cruise_btn)
        cruise_row.addWidget(self.del_cruise_btn)
        layout.addLayout(cruise_row)

        core_row = QtWidgets.QHBoxLayout()
        core_row.addWidget(QtWidgets.QLabel("Core:"))
        self.core_combo = QtWidgets.QComboBox()
        self.core_combo.currentIndexChanged.connect(self._on_core_changed)
        core_row.addWidget(self.core_combo, stretch=1)
        self.add_core_btn = QtWidgets.QPushButton("New Core")
        self.add_core_btn.clicked.connect(self._add_core)
        self.edit_core_btn = QtWidgets.QPushButton("Edit")
        self.edit_core_btn.clicked.connect(self._edit_core)
        self.del_core_btn = QtWidgets.QPushButton("Delete")
        self.del_core_btn.clicked.connect(self._delete_core)
        core_row.addWidget(self.add_core_btn)
        core_row.addWidget(self.edit_core_btn)
        core_row.addWidget(self.del_core_btn)
        layout.addLayout(core_row)

        tabs = QtWidgets.QTabWidget()
        self.sensor_table = QtWidgets.QTableWidget(0, 4)
        self.sensor_table.setHorizontalHeaderLabels(
            ["File", "Location", "Type", "Remarks"]
        )
        self.sensor_table.horizontalHeader().setStretchLastSection(True)
        sensor_btns = QtWidgets.QHBoxLayout()
        add_sensor = QtWidgets.QPushButton("Add Sensor File(s)…")
        add_sensor.clicked.connect(self._add_sensor_files)
        del_sensor = QtWidgets.QPushButton("Remove Selected")
        del_sensor.clicked.connect(self._delete_sensor_file)
        sensor_btns.addWidget(add_sensor)
        sensor_btns.addWidget(del_sensor)
        sensor_btns.addStretch()
        sensor_page = QtWidgets.QWidget()
        sp_layout = QtWidgets.QVBoxLayout(sensor_page)
        sp_layout.addWidget(self.sensor_table)
        sp_layout.addLayout(sensor_btns)
        tabs.addTab(sensor_page, "Sensor Files")

        self.winch_table = QtWidgets.QTableWidget(0, 4)
        self.winch_table.setHorizontalHeaderLabels(
            ["File", "Start", "End", "Notes"]
        )
        self.winch_table.horizontalHeader().setStretchLastSection(True)
        winch_btns = QtWidgets.QHBoxLayout()
        add_winch = QtWidgets.QPushButton("Add Winch File…")
        add_winch.clicked.connect(self._add_winch_file)
        del_winch = QtWidgets.QPushButton("Remove Selected")
        del_winch.clicked.connect(self._delete_winch_file)
        winch_btns.addWidget(add_winch)
        winch_btns.addWidget(del_winch)
        winch_btns.addStretch()
        winch_page = QtWidgets.QWidget()
        wp_layout = QtWidgets.QVBoxLayout(winch_page)
        wp_layout.addWidget(self.winch_table)
        wp_layout.addLayout(winch_btns)
        tabs.addTab(winch_page, "Winch Files (per cruise)")

        layout.addWidget(tabs)
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        for w in (
            self.cruise_combo, self.add_cruise_btn, self.edit_cruise_btn, self.del_cruise_btn,
            self.core_combo, self.add_core_btn, self.edit_core_btn, self.del_core_btn,
        ):
            w.setEnabled(on)

    def _refresh_cruises(self):
        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        if self.store:
            for c in self.store.fetch_cruises():
                label = c["cruise_name"]
                if c.get("vessel_name"):
                    label += f" — {c['vessel_name']}"
                self.cruise_combo.addItem(label, c["cruise_id"])
        self.cruise_combo.blockSignals(False)

    def _refresh_cores(self):
        self.core_combo.blockSignals(True)
        self.core_combo.clear()
        if self.store and self._cruise_id:
            for c in self.store.fetch_cores(self._cruise_id):
                self.core_combo.addItem(c["core_name"], c["core_id"])
        self.core_combo.blockSignals(False)

    def _refresh_sensor_files(self):
        self.sensor_table.setRowCount(0)
        if not self.store or not self._core_id:
            return
        for sf in self.store.fetch_sensor_files(self._core_id):
            row = self.sensor_table.rowCount()
            self.sensor_table.insertRow(row)
            self.sensor_table.setItem(row, 0, QtWidgets.QTableWidgetItem(sf["file_name"]))
            self.sensor_table.setItem(row, 1, QtWidgets.QTableWidgetItem(sf.get("sensor_location") or ""))
            self.sensor_table.setItem(row, 2, QtWidgets.QTableWidgetItem(sf.get("sensor_type") or ""))
            self.sensor_table.setItem(row, 3, QtWidgets.QTableWidgetItem(sf.get("remarks") or ""))
            self.sensor_table.item(row, 0).setData(QtCore.Qt.UserRole, sf["sensor_file_id"])

    def _refresh_winch_files(self):
        self.winch_table.setRowCount(0)
        if not self.store or not self._cruise_id:
            return
        for wf in self.store.fetch_winch_files(self._cruise_id):
            row = self.winch_table.rowCount()
            self.winch_table.insertRow(row)
            self.winch_table.setItem(row, 0, QtWidgets.QTableWidgetItem(wf["file_name"]))
            self.winch_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(wf.get("start_time") or "")))
            self.winch_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(wf.get("end_time") or "")))
            self.winch_table.setItem(row, 3, QtWidgets.QTableWidgetItem(wf.get("notes") or ""))
            self.winch_table.item(row, 0).setData(QtCore.Qt.UserRole, wf["winch_file_id"])

    def _on_cruise_changed(self, index: int):
        self._cruise_id = self.cruise_combo.itemData(index) if index >= 0 else None
        self._core_id = None
        self._refresh_cores()
        self._refresh_sensor_files()
        self._refresh_winch_files()

    def _on_core_changed(self, index: int):
        self._core_id = self.core_combo.itemData(index) if index >= 0 else None
        self._refresh_sensor_files()

    def _add_cruise(self):
        dlg = CruiseDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        name, vessel, notes = dlg.values()
        self.store.add_cruise(name, vessel, notes)
        self._refresh_cruises()
        self.dataChanged.emit()

    def _edit_cruise(self):
        if self._cruise_id is None:
            return
        cruises = {c["cruise_id"]: c for c in self.store.fetch_cruises()}
        cruise = cruises.get(self._cruise_id)
        if not cruise:
            return
        dlg = CruiseDialog(self, cruise)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        name, vessel, notes = dlg.values()
        self.store.update_cruise(self._cruise_id, name, vessel, notes)
        self._refresh_cruises()
        self.dataChanged.emit()

    def _delete_cruise(self):
        if self._cruise_id is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete Cruise", "Delete this cruise and all cores/files?",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self.store.delete_cruise(self._cruise_id)
        self._cruise_id = None
        self._refresh_cruises()
        self._on_cruise_changed(-1)
        self.dataChanged.emit()

    def _add_core(self):
        if self._cruise_id is None:
            QtWidgets.QMessageBox.information(self, "Select Cruise", "Select or create a cruise first.")
            return
        dlg = CoreDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.store.add_core(self._cruise_id, **dlg.values())
        self._refresh_cores()
        self.dataChanged.emit()

    def _edit_core(self):
        if self._core_id is None:
            return
        core = self.store.get_core(self._core_id)
        if not core:
            return
        dlg = CoreDialog(self, core)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.store.update_core(self._core_id, **dlg.values())
        self._refresh_cores()
        self.dataChanged.emit()

    def _delete_core(self):
        if self._core_id is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete Core", "Delete this core and all sensor files?",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self.store.delete_core(self._core_id)
        self._core_id = None
        self._refresh_cores()
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _add_sensor_files(self):
        if self._core_id is None:
            QtWidgets.QMessageBox.information(self, "Select Core", "Select or create a core first.")
            return
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select Sensor Files", "",
            "Sensor files (*.rsk *.dat *.acc *.txt);;All files (*)",
        )
        if not paths:
            return

        loc, ok = QtWidgets.QInputDialog.getItem(
            self, "Sensor Location", "Location:",
            SENSOR_LOCATIONS + ["Other…"], 0, False,
        )
        if not ok:
            return
        if loc == "Other…":
            loc, ok = QtWidgets.QInputDialog.getText(self, "Sensor Location", "Enter location:")
            if not ok or not loc.strip():
                return
            loc = loc.strip()

        stype, ok = QtWidgets.QInputDialog.getText(
            self, "Sensor Type", "Type (optional, e.g. RBR Sensor):",
        )
        if not ok:
            return

        for path in paths:
            try:
                self.store.add_sensor_file(
                    self._core_id, path, sensor_location=loc,
                    sensor_type=stype.strip() or None,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Import Error", f"{path}:\n{exc}")
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _delete_sensor_file(self):
        row = self.sensor_table.currentRow()
        if row < 0:
            return
        fid = self.sensor_table.item(row, 0).data(QtCore.Qt.UserRole)
        self.store.delete_sensor_file(fid)
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _add_winch_file(self):
        if self._cruise_id is None:
            QtWidgets.QMessageBox.information(self, "Select Cruise", "Select a cruise first.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Winch File", "",
            "Winch files (*.dat *.csv *.txt *.raw);;All files (*)",
        )
        if not path:
            return
        dlg = WinchImportDialog(path, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.store.add_winch_file(
            self._cruise_id, path, dlg.settings,
            start_time=dlg.start_time, end_time=dlg.end_time,
            notes=dlg.notes,
        )
        self._refresh_winch_files()
        self.dataChanged.emit()

    def _delete_winch_file(self):
        row = self.winch_table.currentRow()
        if row < 0:
            return
        fid = self.winch_table.item(row, 0).data(QtCore.Qt.UserRole)
        self.store.delete_winch_file(fid)
        self._refresh_winch_files()
        self.dataChanged.emit()

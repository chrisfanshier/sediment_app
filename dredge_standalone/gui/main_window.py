"""Main window: project management + Data Manager / Viewer pages."""
import os

from pyqtgraph.Qt import QtWidgets, QtCore

from ..persistence.project import ProjectStore, DB_FILENAME
from .data_manager import DataManagerPage
from .viewer import ViewerPage

_MAX_RECENT = 8


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dredge App")
        self.resize(1400, 900)

        self.store = None
        self.settings = QtCore.QSettings("DredgeApp", "DredgeApp")

        self.tabs = QtWidgets.QTabWidget()
        self.data_manager = DataManagerPage()
        self.viewer = ViewerPage()
        self.tabs.addTab(self.data_manager, "📂 Data Manager")
        self.tabs.addTab(self.viewer, "📈 Viewer")
        self.setCentralWidget(self.tabs)

        self.viewer.statusMessage.connect(self.statusBar().showMessage)
        self.data_manager.dataChanged.connect(
            lambda: self.viewer.refresh_cruises(keep_selection=True)
        )

        self._create_menu()

        # Reopen the last project if it still exists.
        last = self.settings.value("last_project", "")
        if last and os.path.isdir(last):
            self._open_store(last)
        else:
            self.statusBar().showMessage(
                "No project open — use File ▸ New Project… or Open Project… to begin"
            )

    # ── menu ──────────────────────────────────────────────────────────

    def _create_menu(self):
        menu = self.menuBar().addMenu("File")

        new_action = menu.addAction("New Project…")
        new_action.triggered.connect(self.new_project)

        open_action = menu.addAction("Open Project…")
        open_action.triggered.connect(self.open_project)

        self.recent_menu = menu.addMenu("Recent Projects")
        self._rebuild_recent_menu()

        menu.addSeparator()

        load_usbl_csv = menu.addAction("Load USBL CSV…")
        load_usbl_csv.triggered.connect(self._load_usbl_csv)

        load_sensor_csv = menu.addAction("Load Sensor CSV…")
        load_sensor_csv.triggered.connect(self._load_sensor_csv)

        menu.addSeparator()
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recent = self._recent_projects()
        self.recent_menu.setEnabled(bool(recent))
        for path in recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_store(p))

    def _recent_projects(self) -> list:
        recent = self.settings.value("recent_projects", [])
        if isinstance(recent, str):
            recent = [recent] if recent else []
        return [p for p in recent if os.path.isdir(p)]

    def _remember_project(self, path: str):
        recent = self._recent_projects()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.settings.setValue("recent_projects", recent[:_MAX_RECENT])
        self.settings.setValue("last_project", path)
        self._rebuild_recent_menu()

    # ── project handling ──────────────────────────────────────────────

    def new_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select (or create) an empty folder for the new project"
        )
        if not path:
            return
        contents = [f for f in os.listdir(path) if not f.startswith(".")]
        if contents and DB_FILENAME not in contents:
            reply = QtWidgets.QMessageBox.question(
                self, "Folder Not Empty",
                "The selected folder is not empty and does not look like an "
                "existing project.\n\nCreate a project in it anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._open_store(path)

    def open_project(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Open Project Folder")
        if not path:
            return
        if not os.path.isfile(os.path.join(path, DB_FILENAME)):
            reply = QtWidgets.QMessageBox.question(
                self, "Not a Project",
                f"No {DB_FILENAME} found in this folder.\n\n"
                "Open it as a *new* project?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._open_store(path)

    def _open_store(self, path: str):
        try:
            store = ProjectStore(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, "Project Error", f"Could not open project:\n{exc}"
            )
            return

        if self.store is not None:
            self.store.close()
        self.store = store

        self.data_manager.set_store(store)
        self.viewer.set_store(store)

        self.setWindowTitle(f"Dredge App — {path}")
        self._remember_project(path)

        n_cruises = len(store.fetch_cruises())
        self.statusBar().showMessage(
            f"Project open: {path} ({n_cruises} cruise(s))"
        )

    # ── CSV fallbacks ─────────────────────────────────────────────────

    def _load_usbl_csv(self):
        self.tabs.setCurrentWidget(self.viewer)
        self.viewer.load_usbl_data()

    def _load_sensor_csv(self):
        self.tabs.setCurrentWidget(self.viewer)
        self.viewer.load_sensor_data()

    def closeEvent(self, event):
        if self.store is not None:
            self.store.close()
        event.accept()

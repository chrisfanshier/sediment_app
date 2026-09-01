"""Entry point: ``python -m dredge_standalone``."""
import os
import sys
import tempfile
import traceback

from pyqtgraph.Qt import QtWidgets

from .gui.main_window import MainWindow

CRASH_LOG = os.path.join(tempfile.gettempdir(), "dredge_app_error.log")


def _excepthook(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions and show them in a dialog.

    The app is normally launched with ``pythonw`` (no console), so without
    this hook a crash would be completely invisible to the user.
    """
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 70 + "\n" + text)
    except OSError:
        pass

    sys.__excepthook__(exc_type, exc_value, exc_tb)

    app = QtWidgets.QApplication.instance()
    if app is not None:
        QtWidgets.QMessageBox.critical(
            None,
            "Dredge App — Unexpected Error",
            f"An unexpected error occurred:\n\n{exc_value}\n\n"
            f"Details were written to:\n{CRASH_LOG}",
        )


def main() -> int:
    sys.excepthook = _excepthook
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Dredge App")
    app.setOrganizationName("DredgeApp")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

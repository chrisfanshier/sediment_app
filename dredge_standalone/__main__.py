"""Entry point: ``python -m dredge_standalone``."""
import sys

from pyqtgraph.Qt import QtWidgets

from .gui.main_window import MainWindow


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Dredge App")
    app.setOrganizationName("DredgeApp")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

"""dredge_app package entry point: ``python -m dredge_app``"""
import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import DredgeApp


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = DredgeApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

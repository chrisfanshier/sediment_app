"""recoil_tool package entry point: python -m recoil_tool"""
import sys
from PySide6.QtWidgets import QApplication
from .gui.main_window import MainWindow
from .persistence.recoil_results_io import create_table_if_not_exists


def main():
    create_table_if_not_exists()
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

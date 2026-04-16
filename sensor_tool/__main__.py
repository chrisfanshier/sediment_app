"""sensor_tool package entry point: python -m sensor_tool"""
import sys
from PySide6.QtWidgets import QApplication
from .gui.main_window import MainWindow


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

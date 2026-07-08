import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


def main() -> int:
    """Initialize and start the PySide6 application.

    Returns:
        int: Application exit code.
    """
    # Create the application instance
    app = QApplication(sys.argv)
    app.setApplicationName("PolyGet")
    app.setApplicationVersion("1.0.0")

    # Construct the main window interface
    window = MainWindow()
    window.show()

    # Launch the Qt event loop
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

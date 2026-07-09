import sys


def main() -> int:
    """Initialize and start the application.

    Returns:
        int: Application exit code.
    """
    if "--tui" in sys.argv:
        from app.ui.tui import PolyUpApp
        app = PolyUpApp()
        app.run()
        return 0

    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

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

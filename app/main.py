import sys


def main() -> int:
    """Initialize and start the application.

    Returns:
        int: Application exit code.
    """
    from app.cli import COMMANDS

    # Any subcommand (or --help/--version/--json) routes to the headless CLI, so PySide6 is
    # never imported for scripted or agent use.
    cli_flags = {"-h", "--help", "--version", "--json"}
    if len(sys.argv) > 1 and (sys.argv[1] in COMMANDS or sys.argv[1] in cli_flags):
        from app.cli import main as cli_main
        return cli_main(sys.argv[1:])

    if "--tui" in sys.argv:
        from app.ui.tui import PolyGetTuiApp
        app = PolyGetTuiApp()
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

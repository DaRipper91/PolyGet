import sys
from pathlib import Path


def _icon_candidates() -> list[Path]:
    """Icon files to try, best first.

    SVG first because Qt renders it crisply at any size, PNG as the fallback for
    installs where the Qt SVG image plugin isn't available.
    """
    icon_dir = Path(__file__).resolve().parent.parent / "assets" / "icons"
    candidates = [icon_dir / "polyget.svg"]
    candidates += [icon_dir / f"polyget-{size}.png" for size in (512, 256, 128, 64, 48, 32, 16)]
    return [p for p in candidates if p.exists()]


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

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    # Create the application instance
    app = QApplication(sys.argv)
    app.setApplicationName("PolyGet")
    app.setApplicationVersion("1.0.0")
    app.setDesktopFileName("polyget")

    for icon_path in _icon_candidates():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            app.setWindowIcon(icon)
            break

    # Construct the main window interface
    window = MainWindow()
    window.show()

    # Launch the Qt event loop
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
